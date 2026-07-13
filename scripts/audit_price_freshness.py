#!/usr/bin/env python3
"""Price-freshness audit: trace every security's price through each stage.

    python scripts/audit_price_freshness.py [--csv out.csv] [--live] [--db-url ...]

Stages compared per security:
  live Yahoo quote (only with --live; ~1 min, 79 requests)
  -> stored raw quote file (data/raw/quote_KEY.json)
  -> database raw_quotes row
  -> latest canonical daily bar
  -> price inside the latest published feature snapshot (what Streamlit serves)

Flags exactly where a fresh price stops flowing. Exit code 1 if any CORE
coverage name is stale (>1 session behind its exchange's last completed
session proxy = the freshest quote_date seen for that currency group).
"""
import argparse, csv, glob, json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import connect
from src.utils.universe import load_universe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=None)
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--db-url', default=None)
    a = ap.parse_args()
    u = load_universe()
    core = sorted({k for _, gs in u['subgroups'] for _, cov, _ in gs for k in cov})
    db = connect(a.db_url)
    dbq = {r[0]: (str(r[1]), r[2], str(r[3])) for r in db.fetchall(
        'SELECT key, quote_date, close, refreshed_at FROM raw_quotes')}
    dbbar = {r[0]: str(r[1]) for r in db.fetchall(
        'SELECT key, max(session_date) FROM canonical_prices GROUP BY key')}
    snap = db.fetchall('SELECT snapshot_date, payload FROM app_payload '
                       'ORDER BY snapshot_date DESC LIMIT 1')
    feat_px, feat_date = {}, None
    if snap:
        feat_date = str(snap[0][0])
        pay = json.loads(snap[0][1])
        for r in pay.get('close_rows', []):
            feat_px.setdefault(r['key'], r.get('close_px'))
    live = {}
    if a.live:
        from src.ingestion.yahoo_prices import YahooFinanceAdapter
        import time
        ad = YahooFinanceAdapter()
        for k, sym in u['yahoo'].items():
            try:
                q, _ = ad.get_quote_and_bars(sym, rng='5d')
                live[k] = (q['price'], q['quote_date'])
            except Exception as e:
                live[k] = (None, f'ERR {e!r}'[:60])
            time.sleep(0.5)
    rows = []
    for k, s in u['sec'].items():
        qf = os.path.join(ROOT, 'data', 'raw', f'quote_{k}.json')
        raw_px = raw_dt = None
        if os.path.exists(qf):
            q = json.load(open(qf))
            r = dict(zip(q['columns'], q['results'][0]))
            raw_px, raw_dt = r.get('close'), r.get('datetime')
        d = dbq.get(k, (None, None, None))
        lp, ld = live.get(k, (None, None))
        stages = dict(live=ld, raw=raw_dt, db=d[0], bar=dbbar.get(k),
                      feat=feat_date)
        # freshness: db quote date vs the freshest date seen for its currency
        rows.append(dict(key=k, company=s['name'], yahoo=u['yahoo'].get(k),
                         exchange=s['exch'], ccy=s['qccy'],
                         core=k in core,
                         live_px=lp, live_date=ld,
                         raw_quote_px=raw_px, raw_quote_date=raw_dt,
                         db_quote_px=d[1], db_quote_date=d[0],
                         db_refreshed_at=d[2],
                         latest_bar=dbbar.get(k),
                         feat_px=feat_px.get(k), feat_snapshot=feat_date,
                         mismatch_raw_vs_db=(raw_dt != d[0]),
                         mismatch_db_vs_feat=(
                             feat_px.get(k) is not None and d[1] is not None
                             and abs(float(feat_px[k]) / float(d[1]) - 1) > 5e-4)))
    # staleness: compare each name's db date to the max within its ccy group
    from collections import defaultdict
    latest_by_ccy = defaultdict(str)
    for r in rows:
        if r['db_quote_date']:
            latest_by_ccy[r['ccy']] = max(latest_by_ccy[r['ccy']], r['db_quote_date'])
    stale_core = []
    for r in rows:
        r['stale'] = bool(r['db_quote_date'] and
                          r['db_quote_date'] < latest_by_ccy[r['ccy']])
        if r['stale'] and r['core']:
            stale_core.append(r['key'])
    fresh = sum(1 for r in rows if not r['stale'])
    fresh_core = sum(1 for r in rows if r['core'] and not r['stale'])
    n_core = sum(1 for r in rows if r['core'])
    print(f'freshness: {fresh}/{len(rows)} securities at their currency-group '
          f'latest date | core: {fresh_core}/{n_core}')
    print(f'feature snapshot: {feat_date} | raw-vs-db date mismatches: '
          f"{sum(r['mismatch_raw_vs_db'] for r in rows)} | db-vs-feature px "
          f"mismatches: {sum(r['mismatch_db_vs_feat'] for r in rows)}")
    if stale_core:
        print('STALE CORE:', stale_core)
    for r in rows[:0]:
        pass
    if a.csv:
        with open(a.csv, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print('csv ->', a.csv)
    db.close()
    sys.exit(1 if stale_core else 0)


if __name__ == '__main__':
    main()
