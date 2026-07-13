#!/usr/bin/env python3
"""Single refresh command for the Capital Goods research platform.

    python scripts/refresh.py --mode daily            # normal daily cycle
    python scripts/refresh.py --mode prices_only      # quotes + bars only
    python scripts/refresh.py --mode intraday         # 16:30 UK snapshot
    python scripts/refresh.py --mode fundamentals     # staleness report (FactIQ is interactive)
    python scripts/refresh.py --mode estimates        # alias of fundamentals
    python scripts/refresh.py --mode rebuild_features # engine + load, no fetch
    python scripts/refresh.py --mode validate_only    # checks only
    python scripts/refresh.py --mode full_refresh     # daily + parquet archive

Incremental by construction: prices fetch ~1 month of bars and upsert on
(key, price_date, source); history is never re-downloaded. Idempotent: any
mode can run twice safely. A failed security never stops the others; a
CRITICAL validation failure blocks feature publication.
"""
import argparse, importlib.util, json, os, subprocess, sys, time, uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import connect
from src.validation.checks import run_checks
from src.utils.universe import load_universe

PY = sys.executable


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _select_keys(rp, args):
    keys = list(rp.YAHOO)
    if getattr(args, 'keys', None):
        return [k for k in args.keys if k in rp.YAHOO]
    u = load_universe()
    if getattr(args, 'universe', None) == 'core':
        core = {k for _, gs in u['subgroups'] for _, cov, _ in gs for k in cov}
        keys = [k for k in keys if k in core]
    if getattr(args, 'region', None):
        REGION = {'europe': ('Euronext Paris', 'XETRA', 'SIX', 'Borsa Italiana',
                             'Nasdaq Stockholm', 'Nasdaq Helsinki', 'LSE'),
                  'uk': ('LSE',), 'us': ('NYSE', 'NASDAQ'),
                  'japan': ('JPX Tokyo',)}
        exs = REGION.get(args.region, ())
        keys = [k for k in keys if u['sec'][k]['exch'] in exs]
    if getattr(args, 'failed_only', False):
        p = os.path.join(ROOT, 'data', 'computed', 'last_price_run_stats.json')
        if os.path.exists(p):
            keys = [k for k in json.load(open(p)).get('failed_keys', [])
                    if k in rp.YAHOO]
    return keys


def refresh_prices(db, run_id, args=None):
    """Incremental quotes + daily bars for selected securities + FX."""
    rp = _mod('rp', 'scripts/refresh_prices.py')   # proven fetch/merge logic
    ok = fail = 0
    items = []
    sel = _select_keys(rp, args) if args is not None else list(rp.YAHOO)
    for k in sel:
        try:
            msg = rp.refresh_key(k)
            items.append((run_id, k, 'ok', msg)); ok += 1
        except Exception as e:
            items.append((run_id, k, 'failed', repr(e)[:300])); fail += 1
        time.sleep(0.35)
    for p in rp.FX_PAIRS:
        try:
            items.append((run_id, 'fx_' + p, 'ok', rp.refresh_fx(p))); ok += 1
        except Exception as e:
            items.append((run_id, 'fx_' + p, 'failed', repr(e)[:300])); fail += 1
        time.sleep(0.35)
    db.upsert('refresh_run_items', ['run_id', 'item', 'status', 'message'],
              items, ['run_id', 'item'])
    return ok, fail


def capture_intraday(db, run_id, benchmark='16:30', tz='Europe/London'):
    """Timestamped European-benchmark snapshot (true 16:30 UK price).
    Only meaningful when run shortly after the benchmark time; the GitHub
    Actions intraday workflow handles the DST-aware scheduling."""
    from src.ingestion.yahoo_prices import YahooFinanceAdapter
    u = load_universe()
    eu = {k: v for k, v in u['yahoo'].items()
          if u['sec'][k]['qccy'] in ('EUR', 'GBp', 'CHF', 'SEK')}
    ad = YahooFinanceAdapter()
    rows, fails = [], 0
    for k, sym in eu.items():
        try:
            px, ts, ccy = ad.intraday_price_at(sym, benchmark, tz)
            if px:
                obs = ts[:10]   # the bar's own session date, not the run date
                rows.append((k, obs, f'{benchmark} {tz}', px, ts, None, None,
                             ccy, 'yahoo', 'ok'))
        except Exception:
            fails += 1
        time.sleep(0.3)
    n = db.upsert('eu_close_snapshots',
                  ['key', 'obs_date', 'benchmark_time', 'price', 'price_ts',
                   'later_price', 'later_ts', 'currency', 'source', 'quality'],
                  rows, ['key', 'obs_date', 'benchmark_time'])
    return n, fails


def fill_intraday_later_prices(db):
    """After the daily close refresh, attach the official close to any
    same-day EU snapshot so 'move since 16:30 UK' becomes computable."""
    db.execute("""
        UPDATE eu_close_snapshots SET later_price = q.close, later_ts = q.refreshed_at
        FROM raw_quotes q
        WHERE eu_close_snapshots.key = q.key
          AND eu_close_snapshots.obs_date = q.quote_date
          AND eu_close_snapshots.later_price IS NULL""")


def rebuild_features():
    """Run the validated calculation engine and assemble the static HTML."""
    r = subprocess.run([PY, os.path.join(ROOT, 'scripts', 'compute_metrics.py')],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError('engine failed: ' + r.stderr[-500:])
    tpl = open(os.path.join(ROOT, 'scripts', 'dashboard_template.html')).read()
    data = open(os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')).read()
    html = tpl.replace('__FACTIQ_DATA__', json.dumps({'dash': json.loads(data)}))
    open(os.path.join(ROOT, 'capital_goods_dashboard.html'), 'w').write(html)


def fundamentals_report(db):
    """FactIQ is an interactively-authenticated source: automated runners
    cannot pull it. Report what is stale so a Claude session can refresh it."""
    rows = db.fetchall("""
        SELECT key, kind, max(fetched_at) FROM raw_fundamentals
        WHERE key <> '_UNIVERSE' GROUP BY key, kind ORDER BY 3 LIMIT 15""")
    print('Fundamentals are sourced from FactIQ (interactive session required).')
    print('Oldest stored statement payloads:')
    for k, kind, ts in rows:
        print(f'  {k:8s} {kind:5s} fetched {ts}')
    print('\nTo refresh: open Claude Code in this project and say '
          '"run the quarterly FactIQ refresh".')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='daily',
                    choices=['daily', 'prices_only', 'intraday', 'fundamentals',
                             'estimates', 'full_refresh', 'rebuild_features',
                             'validate_only'])
    ap.add_argument('--db-url', default=None)
    ap.add_argument('--keys', nargs='*', default=None)
    ap.add_argument('--universe', choices=['core', 'all'], default=None)
    ap.add_argument('--region', choices=['europe', 'uk', 'us', 'japan'],
                    default=None)
    ap.add_argument('--failed-only', action='store_true')
    args = ap.parse_args()
    db = connect(args.db_url)
    run_id = f'{args.mode}-{now().strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex[:6]}'
    db.upsert('refresh_runs', ['run_id', 'mode', 'started_at', 'status'],
              [(run_id, args.mode, now(), 'running')], ['run_id'])
    status, inserted, failed, notes = 'success', 0, 0, []
    try:
        if args.mode in ('fundamentals', 'estimates'):
            fundamentals_report(db)
        elif args.mode == 'intraday':
            n, fails = capture_intraday(db, run_id)
            inserted, failed = n, fails
            notes.append(f'{n} EU-close snapshots captured, {fails} failed')
        elif args.mode == 'validate_only':
            pass
        else:
            if args.mode in ('daily', 'prices_only', 'full_refresh'):
                ok, fail = refresh_prices(db, run_id, args)
                failed = fail
                notes.append(f'prices: {ok} ok, {fail} failed')
                if fail > ok:
                    raise RuntimeError('majority of price fetches failed — aborting')
            if args.mode in ('daily', 'full_refresh'):
                # daily = INCREMENTAL (overlap-reconciled, auto full-rebuild
                # per security when a new corporate action lands);
                # full_refresh = complete 5y rebuild.
                cmd = [PY, os.path.join(ROOT, 'scripts', 'backfill_history.py'),
                       '--run-id', run_id]
                if args.mode == 'daily':
                    cmd.append('--recent')
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
                if r.returncode != 0:
                    raise RuntimeError('canonical refresh failed: ' + r.stderr[-300:])
                tail = [l for l in r.stdout.splitlines() if l.strip()][-1:]
                notes.append('canonical: ' + (tail[0] if tail else 'ok'))
            if args.mode in ('daily', 'full_refresh', 'rebuild_features',
                             'prices_only'):
                # prices_only MUST rebuild features (engine ~3s) — publishing
                # the previous dashboard_data.json would republish a stale
                # snapshot as new (bug found+fixed 2026-07-13, v2.6)
                rebuild_features()
                notes.append('features rebuilt')
        # validation gate before publishing features to the DB
        counts = run_checks(db, run_id)
        from src.validation.checks import run_candidate_checks, run_freshness_checks
        cand = run_candidate_checks(db, run_id)
        fresh = run_freshness_checks(db, run_id)
        for k2 in ('critical', 'error', 'warning'):
            cand[k2] = cand.get(k2, 0) + fresh.get(k2, 0)
        for k2 in ('critical', 'error', 'warning'):
            counts[k2] = counts.get(k2, 0) + cand.get(k2, 0)
        notes.append(f"validation: {counts} (incl. candidate gate {cand})")
        if counts.get('critical'):
            status = 'failed'
            notes.append('CRITICAL validation findings — features NOT published')
        elif args.mode in ('daily', 'full_refresh', 'rebuild_features',
                           'prices_only', 'intraday'):
            load = _mod('ld', 'scripts/load_db.py')
            feats_only = args.mode == 'rebuild_features'
            if not feats_only:
                inserted += load.load_prices(db) + load.load_quotes(db) + load.load_fx(db)
                inserted += load.load_canonical(db)
            snap, n = load.load_features(db)
            inserted += n
            from src.screening.events import detect_and_store
            ev = detect_and_store(db, snap)
            fill_intraday_later_prices(db)
            notes.append(f'published snapshot {snap} ({n} feature rows, {ev} change events)')
            if args.mode == 'full_refresh':
                load.export_parquet(db)
                notes.append('parquet archive exported')
        if failed and status == 'success':
            status = 'partial'
    except Exception as e:
        status = 'failed'
        notes.append(repr(e)[:400])
    db.upsert('refresh_runs',
              ['run_id', 'mode', 'started_at', 'finished_at', 'status',
               'rows_inserted', 'items_failed', 'notes'],
              [(run_id, args.mode, now(), now(), status, inserted, failed,
                ' | '.join(notes))], ['run_id'])
    print(f'[{run_id}] {status}: ' + ' | '.join(notes))
    db.close()
    sys.exit(0 if status in ('success', 'partial') else 1)


if __name__ == '__main__':
    main()
