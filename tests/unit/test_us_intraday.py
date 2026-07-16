"""US intraday benchmark + catalyst engine tests. All provider traffic is
mocked (spec §22): a MockFinnhub stands in for the adapter and the Yahoo
fallback is stubbed out — no network, no live API."""
import copy, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.database import db as dbmod
from src.database.db import DB
from src.features import us_intraday as ui
from src.ingestion.finnhub_market_data import (FinnhubEntitlementError,
                                               FinnhubError)

LON = ZoneInfo('Europe/London')

SVC = dict(
    all=['ETN', 'GBX', 'LR'], core=['LR'],
    exch={'ETN': 'NYSE', 'GBX': 'NYSE', 'LR': 'Euronext Paris'},
    qccy={'ETN': 'USD', 'GBX': 'USD', 'LR': 'EUR'},
    finnhub={'ETN': 'ETN', 'GBX': 'GBX'},
    yahoo={'ETN': 'ETN', 'GBX': 'GBX', 'LR': 'LR.PA'},
    names={'ETN': 'Eaton', 'GBX': 'Greenbrier', 'LR': 'Legrand'})


def cfg():
    c = copy.deepcopy(ui.DEFAULTS)
    c['pilot']['universe'] = []          # tests control the universe explicitly
    return c


def tmp_db(monkeypatch):
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tempfile.mktemp(suffix='.duckdb'))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    d = DB()
    d.init_schema()
    return d


def no_yahoo(monkeypatch):
    from src.ingestion.yahoo_prices import YahooFinanceAdapter
    monkeypatch.setattr(YahooFinanceAdapter, 'intraday_price_at',
                        lambda self, *a, **k: (None, None, None))
    monkeypatch.setattr(ui.time, 'sleep', lambda s: None)


class MockFinnhub:
    """Programmable stand-in for FinnhubAdapter — never touches the network."""

    def __init__(self, quotes=None, news=None, candles=None,
                 candle_error=None):
        self.quotes = quotes or {}
        self.news = news or {}
        self.candles = candles or {}
        self.candle_error = candle_error
        self.candle_calls = 0
        self.stats = {'requests': 0, 'ok': 0, 'failed': 0, 'http_429': 0,
                      'retried': 0, 'news_requests': 0}

    def quote(self, symbol):
        self.stats['requests'] += 1
        q = self.quotes.get(symbol)
        if q is None:
            raise FinnhubError('/quote: mock failure')
        return q

    def candles_1m(self, symbol, start, end):
        self.candle_calls += 1
        if self.candle_error:
            raise self.candle_error
        return self.candles.get(symbol, [])

    def company_news(self, symbol, date_from, date_to):
        self.stats['news_requests'] += 1
        return [e for e in self.news.get(symbol, [])
                if date_from <= (e['published_at'] or '')[:10] <= date_to]


def mk_quote(sym, price, ts, prev=None):
    return dict(symbol=sym, price=price, prev_close=prev, high=None, low=None,
                open=None, quote_ts=ts.isoformat(),
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                currency='USD', provider='finnhub')


# ============================= timing & quality =============================

def test_benchmark_target_bst_and_gmt():
    _, t_summer = ui.benchmark_target('2026-07-16')   # London on BST
    assert t_summer == datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)
    _, t_winter = ui.benchmark_target('2026-01-15')   # London on GMT
    assert t_winter == datetime(2026, 1, 15, 16, 30, tzinfo=timezone.utc)


def test_benchmark_target_dst_mismatch_week():
    """US clocks moved 2026-03-08; UK not until 2026-03-29. 16:30 London must
    stay 16:30 UTC while New York reads 12:30 EDT (11:30 in aligned weeks)."""
    _, t = ui.benchmark_target('2026-03-12')
    assert t == datetime(2026, 3, 12, 16, 30, tzinfo=timezone.utc)
    assert t.astimezone(ZoneInfo('America/New_York')).hour == 12
    _, t2 = ui.benchmark_target('2026-04-02')         # both on summer time
    assert t2.astimezone(ZoneInfo('America/New_York')).hour == 11


def test_us_session_open_uses_new_york():
    assert ui.us_session_open(datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc))
    assert not ui.us_session_open(datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc))
    assert not ui.us_session_open(datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc))  # Saturday


def test_quality_tiers():
    _, target = ui.benchmark_target('2026-07-16')
    c = cfg()
    assert ui.classify_quality(target - timedelta(seconds=30), target, c) == 'exact'
    assert ui.classify_quality(target - timedelta(seconds=120), target, c) == 'acceptable'
    assert ui.classify_quality(target - timedelta(seconds=301), target, c) == 'stale'
    assert ui.classify_quality(None, target, c) == 'unavailable'
    c['quality']['exact_within_s'] = 5                # thresholds configurable
    assert ui.classify_quality(target - timedelta(seconds=30), target, c) == 'acceptable'


# ============================= universe & mapping ===========================

def test_us_keys_and_pilot_gate(monkeypatch):
    assert ui.us_keys(SVC) == ['ETN', 'GBX']
    c = cfg()
    c['pilot']['universe'] = ['ETN']
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'pilot')
    assert ui.active_keys(SVC, c) == ['ETN']
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    assert ui.active_keys(SVC, c) == ['ETN', 'GBX']


def test_validate_mappings():
    svc = {k: (dict(v) if isinstance(v, dict) else list(v))
           for k, v in SVC.items()}
    svc['finnhub'] = {'ETN': 'ETN', 'LR': 'ETN'}      # GBX missing, LR duplicate + non-US
    probs = ui.validate_mappings(svc)
    checks = {c for c, _, _ in probs}
    assert 'missing_symbol_mapping' in checks
    assert 'duplicate_finnhub_symbol' in checks
    assert 'unexpected_exchange' in checks and 'currency_mismatch' in checks
    assert ui.validate_mappings(SVC) == []


# ============================= anchor store rules ===========================

def test_anchor_quality_never_downgraded(monkeypatch):
    db = tmp_db(monkeypatch)
    obs, target = ui.benchmark_target('2026-07-16')
    ok = ui.store_anchor(db, 'r1', 'ETN', obs, target, 340.0,
                         target - timedelta(seconds=120), 'finnhub_quote', cfg=cfg())
    assert ok == 'acceptable'
    # a stale Yahoo recovery must NOT replace the acceptable anchor
    assert ui.store_anchor(db, 'r2', 'ETN', obs, target, 300.0,
                           target - timedelta(seconds=900),
                           'yahoo_intraday_fallback', cfg=cfg()) is None
    # an exact websocket trade upgrades it
    assert ui.store_anchor(db, 'r3', 'ETN', obs, target, 341.0,
                           target - timedelta(seconds=10),
                           'finnhub_websocket', cfg=cfg()) == 'exact'
    snap = ui._existing_snaps(db, obs)['ETN']
    assert snap['anchor_price'] == 341.0
    assert snap['anchor_source'] == 'finnhub_websocket'
    assert snap['observation_age_seconds'] == 10
    assert ui.store_anchor(db, 'r4', 'ETN', obs, target, 0, target,
                           'manual', cfg=cfg()) is None   # invalid price rejected


def test_latest_quote_never_older_than_anchor(monkeypatch):
    db = tmp_db(monkeypatch)
    obs, target = ui.benchmark_target('2026-07-16')
    ui.store_anchor(db, 'r1', 'ETN', obs, target, 340.0,
                    target - timedelta(seconds=5), 'finnhub_quote', cfg=cfg())
    # observation BEFORE the anchor: rejected
    assert not ui.store_latest(db, 'r1', 'ETN', obs, target, 339.0,
                               target - timedelta(seconds=600), 'finnhub')
    assert ui.store_latest(db, 'r1', 'ETN', obs, target, 346.2,
                           target + timedelta(hours=1), 'finnhub')
    # regression to an older observation: rejected
    assert not ui.store_latest(db, 'r1', 'ETN', obs, target, 344.0,
                               target + timedelta(minutes=30), 'finnhub')
    snap = ui._existing_snaps(db, obs)['ETN']
    assert snap['latest_price'] == 346.2
    assert round(ui.move_since_benchmark(snap), 4) == round(
        (346.2 / 340.0 - 1) * 100, 4)


def test_move_requires_valid_anchor(monkeypatch):
    db = tmp_db(monkeypatch)
    obs, target = ui.benchmark_target('2026-07-16')
    ui.store_latest(db, 'r1', 'GBX', obs, target, 50.0,
                    target + timedelta(hours=1), 'finnhub')
    snap = ui._existing_snaps(db, obs)['GBX']
    assert snap['anchor_quality'] == 'unavailable'
    assert ui.move_since_benchmark(snap) is None      # never fabricate 0.0%


# ============================= capture paths ================================

def test_capture_anchor_candle_entitlement_fallback(monkeypatch):
    """403 on the first candle call disables Method A for the whole run;
    anchors still land via the REST quote timestamp (Method C)."""
    db = tmp_db(monkeypatch)
    no_yahoo(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()               # today, may be pre-16:30
    ad = MockFinnhub(
        quotes={'ETN': mk_quote('ETN', 340.0, target - timedelta(seconds=90)),
                'GBX': mk_quote('GBX', 50.0, target - timedelta(seconds=200))},
        candle_error=FinnhubEntitlementError('/stock/candle: HTTP 403'))
    m = ui.capture_anchor(db, 'run1', SVC, cfg(), ad, ws_results=None)
    assert ad.candle_calls == 1                       # plan-level: asked once
    assert m['quote'] == 2 and m['candle'] == 0
    snaps = ui._existing_snaps(db, obs)
    assert snaps['ETN']['anchor_source'] == 'finnhub_quote'
    assert snaps['ETN']['anchor_quality'] == 'acceptable'


def test_capture_anchor_websocket_and_candle(monkeypatch):
    db = tmp_db(monkeypatch)
    no_yahoo(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    ad = MockFinnhub(candles={'ETN': [(target - timedelta(seconds=90), 341.5)]})
    ws = {'GBX': {'before': (target - timedelta(seconds=3), 50.25),
                  'after': (target + timedelta(seconds=2), 50.30)}}
    m = ui.capture_anchor(db, 'run1', SVC, cfg(), ad, ws_results=ws)
    snaps = ui._existing_snaps(db, obs)
    assert snaps['ETN']['anchor_source'] == 'finnhub_candle'
    assert snaps['ETN']['anchor_quality'] == 'exact'  # bar closes 30s before
    assert snaps['GBX']['anchor_source'] == 'finnhub_websocket'
    assert snaps['GBX']['anchor_price'] == 50.25      # last trade at/before 16:30
    assert m['candle'] == 1 and m['websocket'] == 1
    assert m['anchored_exact'] == 2


def test_capture_anchor_yahoo_fallback(monkeypatch):
    db = tmp_db(monkeypatch)
    monkeypatch.setattr(ui.time, 'sleep', lambda s: None)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    from src.ingestion.yahoo_prices import YahooFinanceAdapter
    ts = (target - timedelta(seconds=150)).isoformat()
    monkeypatch.setattr(YahooFinanceAdapter, 'intraday_price_at',
                        lambda self, *a, **k: (339.9, ts, 'USD'))
    m = ui.capture_anchor(db, 'run1', SVC, cfg(), adapter=None, keys=['ETN'])
    assert m['yahoo'] == 1
    snap = ui._existing_snaps(db, obs)['ETN']
    assert snap['anchor_source'] == 'yahoo_intraday_fallback'
    assert snap['anchor_quality'] == 'acceptable'


# ============================= quote updates ================================

def test_update_quotes_cross_source_and_currency(monkeypatch):
    db = tmp_db(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    now = datetime.now(timezone.utc)
    # yahoo stored quote observed "now" at a 2% different price -> conflict
    db.upsert('raw_quotes', ['key', 'quote_date', 'close', 'currency',
                             'source', 'refreshed_at'],
              [('ETN', obs, 333.0, 'USD', 'yahoo',
                now.replace(tzinfo=None))], ['key'])
    svc = dict(SVC, qccy=dict(SVC['qccy'], GBX='CAD'))   # force mismatch
    ad = MockFinnhub(quotes={'ETN': mk_quote('ETN', 340.0, now),
                             'GBX': mk_quote('GBX', 50.0, now)})
    m = ui.update_quotes(db, 'run1', svc, cfg(), ad)
    assert m['updated'] == 1 and m['source_conflicts'] == 1
    checks = {(r[0], r[1]) for r in db.fetchall(
        'SELECT check_name, subject FROM validation_results')}
    assert ('cross_source_price_conflict', 'ETN') in checks
    assert ('currency_mismatch', 'GBX') in checks
    snap = ui._existing_snaps(db, obs)['ETN']
    assert snap['latest_price'] == 340.0 and snap['latest_source'] == 'finnhub'


def test_update_quotes_skips_stale_provider_ts(monkeypatch):
    db = tmp_db(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    old = datetime.now(timezone.utc) - timedelta(days=3)   # holiday-stale
    ad = MockFinnhub(quotes={'ETN': mk_quote('ETN', 340.0, old)})
    m = ui.update_quotes(db, 'run1', SVC, cfg(), ad, keys=['ETN'])
    assert m['stale_provider'] == 1 and m['updated'] == 0


# ============================= movers & catalysts ===========================

def seed_moves(db, moves, obs, target):
    for k, (anchor, latest) in moves.items():
        ui.store_anchor(db, 'r', k, obs, target, anchor,
                        target - timedelta(seconds=10), 'finnhub_quote', cfg=cfg())
        ui.store_latest(db, 'r', k, obs, target, latest,
                        target + timedelta(hours=1), 'finnhub')


def test_select_movers_threshold_and_top_n(monkeypatch):
    db = tmp_db(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    svc = dict(SVC, all=['ETN', 'GBX', 'CAT'],
               exch={'ETN': 'NYSE', 'GBX': 'NYSE', 'CAT': 'NYSE'},
               qccy={'ETN': 'USD', 'GBX': 'USD', 'CAT': 'USD'},
               finnhub={'ETN': 'ETN', 'GBX': 'GBX', 'CAT': 'CAT'})
    seed_moves(db, {'ETN': (100, 101.8), 'GBX': (100, 99.95),
                    'CAT': (100, 100.2)}, obs, target)
    c = cfg()
    c['news']['top_movers_each_side'] = 1
    movers, moves = ui.select_movers(db, svc, c)
    assert 'ETN' in movers                     # +1.8% crosses the threshold
    assert 'GBX' in movers                     # top faller even below threshold
    assert round(moves['ETN'], 2) == 1.8
    c['news']['max_symbols_per_run'] = 1
    movers, _ = ui.select_movers(db, svc, c)
    assert movers == ['ETN']                   # cap keeps the biggest mover


def test_catalyst_flow_and_no_catalyst(monkeypatch):
    db = tmp_db(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    after = (target + timedelta(minutes=42)).isoformat()
    before = (target - timedelta(hours=3)).isoformat()
    ad = MockFinnhub(news={'ETN': [
        dict(provider='finnhub', provider_event_id='101', symbol='ETN',
             headline='Eaton announces data-centre order', summary='s',
             source='Reuters', url='https://x/1', published_at=after,
             category='company', related='ETN',
             retrieved_at=datetime.now(timezone.utc).isoformat()),
        dict(provider='finnhub', provider_event_id='100', symbol='ETN',
             headline='Morning wrap', summary='', source='Wire',
             url='https://x/0', published_at=before, category='company',
             related='ETN', retrieved_at=datetime.now(timezone.utc).isoformat()),
    ]})
    m = ui.fetch_catalysts(db, 'run1', SVC, cfg(), ad, ['ETN', 'GBX'])
    assert m['events'] == 2 and m['no_news'] == 1
    # re-run: idempotent, no duplicates
    ui.fetch_catalysts(db, 'run1', SVC, cfg(), ad, ['ETN'])
    assert db.fetchall('SELECT count(*) FROM market_events')[0][0] == 2
    cols = ['key', 'published_at', 'headline', 'relevance_score', 'after_1630_uk']
    rows = [dict(zip(cols, r)) for r in db.fetchall(
        f'SELECT {", ".join(cols)} FROM market_events WHERE key = \'ETN\'')]
    pick = ui.pick_catalyst(rows, target)
    assert pick['headline'] == 'Eaton announces data-centre order'
    assert bool(pick['after_1630_uk']) is True
    assert ui.pick_catalyst([], target) is None       # explicit no-catalyst


# ============================= end-to-end ===================================

def test_integration_quote_to_basket_readacross(monkeypatch):
    """Mock Finnhub quote -> database -> benchmark move -> equal-weight peer
    basket -> the shape Market & Peers renders (spec §22 integration)."""
    db = tmp_db(monkeypatch)
    no_yahoo(monkeypatch)
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    obs, target = ui.benchmark_target()
    ad = MockFinnhub(
        quotes={'ETN': mk_quote('ETN', 340.0, target - timedelta(seconds=30)),
                'GBX': mk_quote('GBX', 50.0, target - timedelta(seconds=45))})
    ui.capture_anchor(db, 'run1', SVC, cfg(), ad, use_candles=False)
    later = datetime.now(timezone.utc) if datetime.now(timezone.utc) > target \
        else target + timedelta(hours=1)
    ad.quotes = {'ETN': mk_quote('ETN', 346.12, later),
                 'GBX': mk_quote('GBX', 49.80, later)}
    ui.update_quotes(db, 'run1', SVC, cfg(), ad)
    snaps = ui._existing_snaps(db, obs)
    moves = {k: ui.move_since_benchmark(s) for k, s in snaps.items()}
    assert round(moves['ETN'], 2) == 1.8 and round(moves['GBX'], 2) == -0.4
    basket = sum(moves.values()) / len(moves)          # equal-weight read-across
    assert round(basket, 2) == 0.7
    assert all(s['anchor_quality'] == 'exact' for s in snaps.values())
    ui.record_metrics(db, 'run1', 'quotes', {'updated': 2}, ad)
    assert db.fetchall("SELECT count(*) FROM refresh_run_items "
                       "WHERE item = 'finnhub_quotes'")[0][0] == 1
