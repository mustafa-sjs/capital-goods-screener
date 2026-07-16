"""US intraday benchmark + catalyst engine ("US since Europe closed").

Answers one business question: how have the US peers moved since 16:30 UK
time, and is there a company-specific update behind a material move?

Data model (schema.sql):
  market_benchmark_snapshots  one row per (key, US session, benchmark) with
                              the 16:30 UK anchor AND the latest observation,
                              each carrying source + quality + timestamps.
  intraday_quote_snapshots    small audit trail of periodic quote updates.
  market_events               company-news metadata for catalyst display.

Anchor methods, in precedence order (a worse observation never overwrites a
better one — see QUALITY_RANK):
  finnhub_candle             completed 1-minute bar at 16:30 (needs paid
                             entitlement; 403 detected and skipped cleanly)
  finnhub_websocket          last trade at/before 16:30 from a short-lived
                             capture window (batch job only)
  finnhub_quote              REST quote taken around 16:30 whose own trade
                             timestamp dates the observation
  yahoo_intraday_fallback    the existing 5-minute-bar mechanism

All benchmark times are defined in Europe/London and converted with zoneinfo
(never a fixed UTC offset); US session status uses America/New_York.
Timestamps are stored in the database as naive UTC, matching the platform
convention.
"""
import json, os, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG_PATH = os.path.join(ROOT, 'config', 'finnhub.yaml')
LONDON, NEW_YORK = ZoneInfo('Europe/London'), ZoneInfo('America/New_York')

BENCHMARK_NAME = 'european_close_1630_uk'
QUALITY_RANK = {'exact': 3, 'acceptable': 2, 'stale': 1, 'unavailable': 0}
US_EXCHANGES = ('NYSE', 'NASDAQ')

SNAP_COLS = ['key', 'observation_date', 'benchmark_name', 'target_ts',
             'anchor_price', 'anchor_ts', 'latest_price', 'latest_ts',
             'currency', 'anchor_source', 'latest_source', 'anchor_quality',
             'observation_age_seconds', 'run_id', 'updated_at']
SNAP_KEYS = ['key', 'observation_date', 'benchmark_name']

DEFAULTS = dict(
    quality=dict(exact_within_s=60, acceptable_before_s=300),
    rate_limit=dict(max_requests_per_minute=30),
    news=dict(min_abs_move_pct=1.0, top_movers_each_side=5,
              fallback_lookback_days=3, max_symbols_per_run=20),
    websocket=dict(enabled=True, open_before_s=240, close_after_s=90,
                   max_symbols=50),
    benchmark=dict(name=BENCHMARK_NAME, time_local='16:30',
                   timezone='Europe/London'),
    pilot=dict(universe=[]),
)


def load_cfg(path=CFG_PATH):
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    try:
        import yaml
        raw = yaml.safe_load(open(path)) or {}
        for sect, vals in raw.items():
            if isinstance(vals, dict):
                cfg.setdefault(sect, {}).update(vals)
    except Exception:
        pass                       # defaults keep every job functional
    return cfg


# ============================= universe & mapping ===========================

def us_keys(svc):
    """US securities the Market & Peers page can need (coverage or basket
    peer, NYSE/NASDAQ listings)."""
    return sorted(k for k in svc['all'] if svc['exch'].get(k) in US_EXCHANGES)


def active_keys(svc, cfg, keys=None):
    """Requested universe, narrowed to mapped US names — and to the pilot
    universe unless FINNHUB_USAGE_MODE=production."""
    from src.ingestion.finnhub_market_data import usage_mode
    ks = [k for k in (keys or us_keys(svc)) if k in svc['finnhub']]
    if usage_mode() == 'pilot':
        pilot = set(cfg.get('pilot', {}).get('universe') or [])
        if pilot:
            ks = [k for k in ks if k in pilot]
    return ks


def validate_mappings(svc):
    """Symbol-mapping problems, visibly reported (Data Status) rather than
    silently excluded. Returns [(check_name, subject, message)]."""
    problems = []
    fh = svc['finnhub']
    for k in us_keys(svc):
        if k not in fh:
            problems.append(('missing_symbol_mapping', k,
                             'active US peer has no finnhub_symbol in the coverage pack'))
    rev = {}
    for k, sym in fh.items():
        if sym in rev:
            problems.append(('duplicate_finnhub_symbol', k,
                             f'finnhub_symbol {sym} already used by {rev[sym]}'))
        rev[sym] = k
    for k in fh:
        if svc['exch'].get(k) not in US_EXCHANGES:
            problems.append(('unexpected_exchange', k,
                             f"finnhub_symbol set but exchange is {svc['exch'].get(k)}"))
        if svc['qccy'].get(k) != 'USD':
            problems.append(('currency_mismatch', k,
                             f"finnhub layer expects USD, reference says {svc['qccy'].get(k)}"))
    return problems


# ============================= benchmark timing =============================

def benchmark_target(session_date=None, cfg=None):
    """(session_date_iso, aware target datetime in UTC). The benchmark is
    16:30 in Europe/London on the given date — DST comes from zoneinfo."""
    cfg = cfg or load_cfg()
    hh, mm = map(int, cfg['benchmark']['time_local'].split(':'))
    tz = ZoneInfo(cfg['benchmark']['timezone'])
    if session_date is None:
        session_date = datetime.now(tz).date()
    elif isinstance(session_date, str):
        session_date = datetime.strptime(session_date, '%Y-%m-%d').date()
    local = datetime(session_date.year, session_date.month, session_date.day,
                     hh, mm, tzinfo=tz)
    return session_date.isoformat(), local.astimezone(timezone.utc)


def us_session_open(at_utc=None):
    """Regular NYSE hours in America/New_York (weekday 09:30-16:00). A
    conservative guard — holidays simply produce no fresh quotes and the
    stale-quote validation catches them."""
    now = (at_utc or datetime.now(timezone.utc)).astimezone(NEW_YORK)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= mins < 16 * 60


def classify_quality(anchor_ts, target_utc, cfg=None):
    """Anchor quality per the configurable rules: exact within ±exact_within_s
    of the target; acceptable up to acceptable_before_s away; stale beyond
    that; unavailable when there is no valid observation."""
    if anchor_ts is None:
        return 'unavailable'
    cfg = cfg or load_cfg()
    q = cfg['quality']
    gap = abs((target_utc - _aware_utc(anchor_ts)).total_seconds())
    if gap <= q['exact_within_s']:
        return 'exact'
    if gap <= q['acceptable_before_s']:
        return 'acceptable'
    return 'stale'


def _aware_utc(ts):
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _naive_utc(ts):
    return _aware_utc(ts).astimezone(timezone.utc).replace(tzinfo=None) if ts else None


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================= snapshot store ===============================

def _existing_snaps(db, obs_date):
    rows = db.fetchall(
        f'SELECT {", ".join(SNAP_COLS)} FROM market_benchmark_snapshots '
        f'WHERE observation_date = {db.ph} AND benchmark_name = {db.ph}',
        [obs_date, BENCHMARK_NAME])
    return {r[0]: dict(zip(SNAP_COLS, r)) for r in rows}


def store_anchor(db, run_id, key, obs_date, target_utc, price, anchor_ts,
                 source, currency='USD', cfg=None):
    """Upsert one anchor observation; a lower-quality observation NEVER
    replaces a higher-quality stored one. Returns the stored quality or None
    when skipped."""
    quality = classify_quality(anchor_ts, target_utc, cfg)
    if price is None or price <= 0 or quality == 'unavailable':
        return None
    cur = _existing_snaps(db, obs_date).get(key)
    if cur and QUALITY_RANK.get(cur['anchor_quality'], 0) >= QUALITY_RANK[quality]:
        return None
    age = int((target_utc - _aware_utc(anchor_ts)).total_seconds())
    row = dict(cur or {}, key=key, observation_date=obs_date,
               benchmark_name=BENCHMARK_NAME, target_ts=_naive_utc(target_utc),
               anchor_price=float(price), anchor_ts=_naive_utc(anchor_ts),
               currency=currency, anchor_source=source, anchor_quality=quality,
               observation_age_seconds=age, run_id=run_id, updated_at=_now())
    for c in ('latest_price', 'latest_ts', 'latest_source'):
        row.setdefault(c, None)
    db.upsert('market_benchmark_snapshots', SNAP_COLS,
              [tuple(row[c] for c in SNAP_COLS)], SNAP_KEYS)
    return quality


def store_latest(db, run_id, key, obs_date, target_utc, price, quote_ts,
                 source, prev_close=None, currency='USD'):
    """Record a current observation: audit row + snapshot latest_*. The
    latest price is never regressed to an observation older than the stored
    one, and never predates the anchor."""
    if price is None or price <= 0:
        return False
    ts = _naive_utc(quote_ts)
    db.upsert('intraday_quote_snapshots',
              ['key', 'quote_ts', 'price', 'previous_close', 'currency',
               'source', 'quality', 'run_id', 'ingested_at'],
              [(key, ts, float(price), prev_close, currency, source, 'ok',
                run_id, _now())], ['key', 'quote_ts', 'source'])
    cur = _existing_snaps(db, obs_date).get(key)
    if cur:
        if cur['latest_ts'] and ts <= cur['latest_ts']:
            return False
        if cur['anchor_ts'] and ts < cur['anchor_ts']:
            return False
    row = dict(cur or dict.fromkeys(SNAP_COLS),
               key=key, observation_date=obs_date, benchmark_name=BENCHMARK_NAME,
               target_ts=(cur or {}).get('target_ts') or _naive_utc(target_utc),
               latest_price=float(price), latest_ts=ts, latest_source=source,
               currency=currency, run_id=run_id, updated_at=_now())
    row.setdefault('anchor_quality', None)
    if not row.get('anchor_quality'):
        row['anchor_quality'] = 'unavailable'
    db.upsert('market_benchmark_snapshots', SNAP_COLS,
              [tuple(row[c] for c in SNAP_COLS)], SNAP_KEYS)
    return True


def move_since_benchmark(snap):
    """move_since_1630_pct for one snapshot dict/row — None unless a usable
    anchor AND a strictly later observation exist (never fabricate 0.0%)."""
    if not snap:
        return None
    a, l = snap.get('anchor_price'), snap.get('latest_price')
    if not a or not l or snap.get('anchor_quality') in (None, 'unavailable'):
        return None
    if snap.get('latest_ts') and snap.get('anchor_ts') \
            and snap['latest_ts'] <= snap['anchor_ts']:
        return None
    return (l / a - 1) * 100


# ============================= anchor capture ===============================

def capture_anchor(db, run_id, svc, cfg, adapter=None, keys=None,
                   session_date=None, use_candles=True, ws_results=None):
    """Capture or recover the 16:30 UK anchor for the active US universe.
    Precedence: 1-minute candle -> websocket capture (ws_results from the
    pre-16:30 job) -> REST quote timestamp -> Yahoo intraday fallback.
    Idempotent; only ever upgrades stored quality. Returns metrics dict."""
    from src.ingestion import finnhub_market_data as fmd
    obs_date, target_utc = benchmark_target(session_date, cfg)
    ks = active_keys(svc, cfg, keys)
    m = {'requested': len(ks), 'candle': 0, 'websocket': 0, 'quote': 0,
         'yahoo': 0, 'skipped_existing': 0, 'unusable': 0, 'errors': 0}
    existing = _existing_snaps(db, obs_date)
    candles_entitled = use_candles and adapter is not None
    for k in ks:
        cur = existing.get(k)
        if cur and cur['anchor_quality'] == 'exact':
            m['skipped_existing'] += 1
            continue
        sym = svc['finnhub'][k]
        stored = None
        # Method A — completed 1-minute bar around the benchmark
        if candles_entitled:
            try:
                bars = adapter.candles_1m(sym, target_utc.timestamp() - 360,
                                          target_utc.timestamp() + 120)
                pick = [(t + timedelta(seconds=60), c) for t, c in bars
                        if t + timedelta(seconds=60) <= target_utc]  # bar close time
                if pick:
                    ts, px = pick[-1]
                    if store_anchor(db, run_id, k, obs_date, target_utc, px,
                                    ts, 'finnhub_candle', cfg=cfg):
                        m['candle'] += 1
                        continue
            except fmd.FinnhubAuthError:
                raise                          # bad key: abort the whole run
            except fmd.FinnhubEntitlementError:
                candles_entitled = False       # plan-level: stop asking
            except fmd.FinnhubError:
                m['errors'] += 1
        # Method B — websocket capture results from the pre-16:30 window
        if ws_results and sym in ws_results:
            obs = ws_results[sym].get('before') or ws_results[sym].get('after')
            if obs and store_anchor(db, run_id, k, obs_date, target_utc,
                                    obs[1], obs[0], 'finnhub_websocket', cfg=cfg):
                m['websocket'] += 1
                continue
        # Method C — REST quote whose own trade timestamp dates the observation
        if adapter is not None:
            try:
                q = adapter.quote(sym)
                qts = _aware_utc(q['quote_ts'])
                if abs((target_utc - qts).total_seconds()) <= 900 and \
                        store_anchor(db, run_id, k, obs_date, target_utc,
                                     q['price'], qts, 'finnhub_quote', cfg=cfg):
                    m['quote'] += 1
                    continue
            except fmd.FinnhubAuthError:
                raise
            except fmd.FinnhubError:
                m['errors'] += 1
        # Method D — existing Yahoo 5-minute-bar recovery
        try:
            from src.ingestion.yahoo_prices import YahooFinanceAdapter
            px, ts, ccy = YahooFinanceAdapter().intraday_price_at(
                svc['yahoo'][k], cfg['benchmark']['time_local'],
                cfg['benchmark']['timezone'])
            time.sleep(0.3)
            if px and ts and store_anchor(db, run_id, k, obs_date, target_utc,
                                          px, ts, 'yahoo_intraday_fallback',
                                          currency=ccy or 'USD', cfg=cfg):
                m['yahoo'] += 1
                continue
        except Exception:
            m['errors'] += 1
        m['unusable'] += 1
    m.update(anchor_coverage(db, obs_date))
    return m


def ws_anchor_capture(svc, cfg, keys=None, session_date=None):
    """Benchmark Method B driver: short-lived trade capture bracketing 16:30
    UK. Returns Finnhub-symbol-keyed results for capture_anchor, or None when
    the websockets package (Actions-job-only dependency) is unavailable."""
    from src.ingestion.finnhub_market_data import capture_trades_around
    if not cfg['websocket'].get('enabled', True):
        return None
    obs_date, target_utc = benchmark_target(session_date, cfg)
    stop = target_utc + timedelta(seconds=cfg['websocket']['close_after_s'])
    if datetime.now(timezone.utc) >= stop:
        return None                       # window already passed — recovery paths handle it
    syms = [svc['finnhub'][k] for k in active_keys(svc, cfg, keys)]
    return capture_trades_around(syms, target_utc, stop,
                                 max_symbols=cfg['websocket']['max_symbols'])


def anchor_coverage(db, obs_date):
    rows = db.fetchall(
        f'SELECT anchor_quality, count(*) FROM market_benchmark_snapshots '
        f'WHERE observation_date = {db.ph} AND benchmark_name = {db.ph} '
        f'GROUP BY anchor_quality', [obs_date, BENCHMARK_NAME])
    d = {(q or 'unavailable'): n for q, n in rows}
    return {'anchored_exact': d.get('exact', 0),
            'anchored_acceptable': d.get('acceptable', 0),
            'anchored_stale': d.get('stale', 0),
            'anchor_unavailable': d.get('unavailable', 0)}


# ============================= quote updates ================================

def update_quotes(db, run_id, svc, cfg, adapter, keys=None, session_date=None):
    """Periodic current-price update for the active US universe, with
    cross-source comparison against the stored Yahoo quote."""
    from src.ingestion import finnhub_market_data as fmd
    obs_date, target_utc = benchmark_target(session_date, cfg)
    ks = active_keys(svc, cfg, keys)
    m = {'requested': len(ks), 'updated': 0, 'failed': 0, 'stale_provider': 0,
         'source_conflicts': 0}
    checks = []
    yahoo = {r[0]: r for r in db.fetchall(
        'SELECT key, close, refreshed_at, currency FROM raw_quotes')}
    for k in ks:
        try:
            q = adapter.quote(svc['finnhub'][k])
        except fmd.FinnhubAuthError:
            raise
        except fmd.FinnhubError:
            m['failed'] += 1
            continue
        qts = _aware_utc(q['quote_ts'])
        if (datetime.now(timezone.utc) - qts).total_seconds() > 24 * 3600:
            m['stale_provider'] += 1       # holiday/closed listing — skip
            continue
        if q['currency'] != svc['qccy'].get(k):
            checks.append(('currency_mismatch', k,
                           f"finnhub USD vs reference {svc['qccy'].get(k)}"))
            continue
        if store_latest(db, run_id, k, obs_date, target_utc, q['price'], qts,
                        'finnhub', prev_close=q['prev_close']):
            m['updated'] += 1
        y = yahoo.get(k)
        if y and y[1]:
            gap = abs((qts.replace(tzinfo=None) - y[2]).total_seconds()) \
                if y[2] else None
            diff = abs(q['price'] / y[1] - 1) * 100
            if gap is not None and gap <= 60 and diff > 1.0:
                checks.append(('cross_source_price_conflict', k,
                               f'finnhub {q["price"]} vs yahoo {y[1]} '
                               f'({diff:.1f}% apart, timestamps within 60s)'))
                m['source_conflicts'] += 1
            elif diff > 2.0:
                checks.append(('cross_source_timestamp_gap', k,
                               f'finnhub {q["price"]} vs yahoo {y[1]} differ '
                               f'{diff:.1f}% but timestamps are '
                               f'{"unknown" if gap is None else int(gap)}s apart '
                               f'— price movement, not a provider conflict'))
    _emit_checks(db, run_id, checks)
    return m


def _emit_checks(db, run_id, checks, severity='warning'):
    if not checks:
        return
    sev = {'cross_source_timestamp_gap': 'info'}
    db.upsert('validation_results',
              ['run_id', 'check_name', 'severity', 'subject', 'message',
               'created_at'],
              [(run_id, c, sev.get(c, severity), s, msg, _now())
               for c, s, msg in checks],
              ['run_id', 'check_name', 'subject'])


# ============================= catalysts ====================================

def select_movers(db, svc, cfg, keys=None, session_date=None):
    """US names whose |move since 16:30 UK| crosses the configured threshold,
    plus the top N gainers and fallers regardless — capped, deduplicated."""
    obs_date, _ = benchmark_target(session_date, cfg)
    ks = set(active_keys(svc, cfg, keys))
    moves = {}
    for k, snap in _existing_snaps(db, obs_date).items():
        if k in ks:
            mv = move_since_benchmark(snap)
            if mv is not None:
                moves[k] = mv
    n = cfg['news']['top_movers_each_side']
    ranked = sorted(moves, key=lambda k: moves[k])
    picked = {k for k in moves if abs(moves[k]) >= cfg['news']['min_abs_move_pct']}
    picked |= set(ranked[:n]) | set(ranked[-n:])
    cap = cfg['news']['max_symbols_per_run']
    return sorted(picked, key=lambda k: -abs(moves[k]))[:cap], moves


def fetch_catalysts(db, run_id, svc, cfg, adapter, keys, session_date=None):
    """Company news for the given keys: session-day window first, then the
    configured lookback when the day is empty. Metadata only; deduplicated
    on (provider, provider_event_id)."""
    from src.ingestion import finnhub_market_data as fmd
    obs_date, target_utc = benchmark_target(session_date, cfg)
    m = {'requested': len(keys), 'events': 0, 'no_news': 0, 'failed': 0}
    for k in keys:
        sym = svc['finnhub'].get(k)
        if not sym:
            continue
        try:
            events = adapter.company_news(sym, obs_date, obs_date)
            if not events:
                start = (datetime.strptime(obs_date, '%Y-%m-%d')
                         - timedelta(days=cfg['news']['fallback_lookback_days']))
                events = adapter.company_news(sym, start.strftime('%Y-%m-%d'),
                                              obs_date)
        except fmd.FinnhubAuthError:
            raise
        except fmd.FinnhubError:
            m['failed'] += 1
            continue
        if not events:
            m['no_news'] += 1
            continue
        rows = []
        for e in events[:25]:
            pub = _aware_utc(e['published_at']) if e['published_at'] else None
            rows.append((e['provider'], e['provider_event_id'], k, e['symbol'],
                         _naive_utc(pub), e['headline'], e['summary'],
                         e['source'], e['url'], e['category'], e['related'],
                         _now(), pub.date().isoformat() if pub else None,
                         bool(pub and pub > target_utc),
                         _relevance(e, sym, pub, target_utc)))
        m['events'] += db.upsert('market_events',
                                 ['provider', 'provider_event_id', 'key',
                                  'symbol', 'published_at', 'headline',
                                  'summary', 'source_name', 'article_url',
                                  'category', 'related_symbol', 'retrieved_at',
                                  'event_date', 'after_1630_uk',
                                  'relevance_score'],
                                 rows, ['provider', 'provider_event_id'])
    return m


def _relevance(e, sym, pub, target_utc):
    """Transparent, documented ranking — no opaque causality model:
    +2 published after the 16:30 UK benchmark, +1 provider ties the article
    to this ticker, +1 company-news category, minus staleness in days."""
    score = 0.0
    if pub and pub > target_utc:
        score += 2
    if e.get('related') and sym in str(e['related']).split(','):
        score += 1
    if (e.get('category') or '') == 'company':
        score += 1
    if pub:
        score -= min((datetime.now(timezone.utc) - pub).days, 7) * 0.5
    return score


def pick_catalyst(events, target_utc):
    """The single displayed update for one security: prefer the most relevant
    event published AFTER the benchmark, else the most recent before it.
    events = market_events dict rows; returns a dict or None."""
    scored = [e for e in events if e.get('published_at')]
    if not scored:
        return None
    after = [e for e in scored if _aware_utc(e['published_at']) > target_utc]
    pool = after or scored
    return max(pool, key=lambda e: (e.get('relevance_score') or 0,
                                    _aware_utc(e['published_at'])))


# ============================= run metrics ==================================

def record_metrics(db, run_id, stage, metrics, adapter=None):
    """One refresh_run_items row per stage with the JSON metrics payload —
    the Data Status page renders these. Never includes secrets."""
    payload = dict(metrics)
    if adapter is not None:
        payload['api'] = adapter.stats
    db.upsert('refresh_run_items', ['run_id', 'item', 'status', 'message'],
              [(run_id, f'finnhub_{stage}', 'ok', json.dumps(payload)[:900])],
              ['run_id', 'item'])
