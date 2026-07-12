#!/usr/bin/env python3
"""Load/refresh the persistent database from the file-based data layer.

Idempotent: every write is an upsert on a natural key — safe to run twice.

Loads:
  - securities + coverage groups/members  <- config/coverage_packs/*.yaml
  - raw_daily_prices / raw_monthly_prices <- data/raw/daily_*.json, monthly_*.json
  - raw_quotes                            <- data/raw/quote_*.json
  - raw_fx_rates                          <- data/raw/fx_*.json
  - raw_fundamentals                      <- data/raw/{isa,isq,bsa,bsq,cfa,cfq,sec}_*.json
  - feature tables + app_payload          <- data/computed/dashboard_data.json
  - daily_change_events                   <- diff vs previous feat_screener snapshot

Usage: python scripts/load_db.py [--db-url postgresql://...] [--features-only]
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
RAW = os.path.join(ROOT, 'data', 'raw')
from src.database.db import connect
from src.utils.universe import load_universe

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def f(x):
    try:
        return float(x) if x not in (None, '', 'None') else None
    except (TypeError, ValueError):
        return None


def load_reference(db, u):
    rows = [(k, s['name'], s['sym'], s['exch'], s['qccy'], s['rccy'],
             u['yahoo'].get(k), True) for k, s in u['sec'].items()]
    n = db.upsert('securities',
                  ['key', 'name', 'ticker', 'exchange', 'quote_ccy', 'report_ccy',
                   'yahoo_symbol', 'active'], rows, ['key'])
    grows, mrows = [], []
    for sg, groups in u['subgroups']:
        for disp, cov, peers in groups:
            gid = re.sub(r'[^a-z0-9]+', '-', disp.lower()).strip('-')
            grows.append((gid, u.get('pack') or 'capital_goods', sg, disp))
            mrows += [(gid, k, 'coverage', i) for i, k in enumerate(cov)]
            mrows += [(gid, k, 'peer', i) for i, k in enumerate(peers)]
    n += db.upsert('coverage_groups', ['group_id', 'pack', 'subgroup', 'display'],
                   grows, ['group_id'])
    n += db.upsert('coverage_members', ['group_id', 'key', 'role', 'position'],
                   mrows, ['group_id', 'key', 'role'])
    return n


def load_prices(db):
    n = 0
    for path in glob.glob(os.path.join(RAW, 'daily_*.json')):
        k = os.path.basename(path)[6:-5]
        d = json.load(open(path))
        src = 'yahoo' if d.get('refresh_source') else 'factiq'
        rows = [(k, r[0], f(r[1]), f(r[2]), f(r[3]), f(r[4]),
                 int(float(r[5])) if len(r) > 5 and r[5] not in ('', None) else None,
                 d.get('currency'), 'mixed' if src == 'yahoo' else 'factiq', NOW, 'ok')
                for r in d.get('results', []) if r and f(r[4]) is not None]
        n += db.upsert('raw_daily_prices',
                       ['key', 'price_date', 'open', 'high', 'low', 'close', 'volume',
                        'currency', 'source', 'ingested_at', 'quality'],
                       rows, ['key', 'price_date', 'source'])
    for path in glob.glob(os.path.join(RAW, 'monthly_*.json')):
        k = os.path.basename(path)[8:-5]
        d = json.load(open(path))
        rows = [(k, r[0], f(r[4]), d.get('currency'), 'factiq')
                for r in d.get('results', []) if r and f(r[4]) is not None]
        n += db.upsert('raw_monthly_prices',
                       ['key', 'price_date', 'close', 'currency', 'source'],
                       rows, ['key', 'price_date', 'source'])
    return n


def load_quotes(db):
    rows = []
    for path in glob.glob(os.path.join(RAW, 'quote_*.json')):
        k = os.path.basename(path)[6:-5]
        q = json.load(open(path))
        if not q.get('results'):
            continue
        r = dict(zip(q['columns'], q['results'][0]))
        rows.append((k, r.get('datetime'), f(r.get('close')), f(r.get('previous_close')),
                     f(r.get('fifty_two_week.high')), f(r.get('fifty_two_week.low')),
                     q.get('currency'),
                     'yahoo' if q.get('refresh_source') else 'factiq', NOW))
    return db.upsert('raw_quotes',
                     ['key', 'quote_date', 'close', 'prev_close', 'high_52w', 'low_52w',
                      'currency', 'source', 'refreshed_at'], rows, ['key'])


def load_fx(db):
    n = 0
    for path in glob.glob(os.path.join(RAW, 'fx_*.json')):
        pair = os.path.basename(path)[3:-5]
        d = json.load(open(path))
        rows = [(pair, r[0], f(r[4]), 'mixed') for r in d.get('results', [])
                if r and f(r[4]) is not None]
        n += db.upsert('raw_fx_rates', ['pair', 'rate_date', 'close', 'source'],
                       rows, ['pair', 'rate_date', 'source'])
    return n


def load_fundamentals(db):
    rows = []
    for path in glob.glob(os.path.join(RAW, '*.json')):
        base = os.path.basename(path)[:-5]
        m = re.match(r'(isa|isq|bsa|bsq|cfa|cfq)_(\w+)$', base)
        if m:
            rows.append((m.group(2), m.group(1), open(path).read(), NOW))
        elif base.startswith('sec_'):
            rows.append(('_UNIVERSE', base, open(path).read(), NOW))
    return db.upsert('raw_fundamentals', ['key', 'kind', 'payload', 'fetched_at'],
                     rows, ['key', 'kind'])


def load_canonical(db):
    import pandas as pd
    hist = os.path.join(ROOT, 'data', 'history')
    p = os.path.join(hist, 'prices_daily.parquet')
    if not os.path.exists(p):
        return 0
    df = pd.read_parquet(p).astype(object).where(lambda x: pd.notnull(x), None)
    n = db.upsert('canonical_prices',
                  ['key', 'session_date', 'close_raw', 'close_split', 'close_tr',
                   'volume', 'currency', 'exchange_tz', 'source', 'complete'],
                  [(r.key, r.session_date, r.close_raw, r.close_split, r.close_tr,
                    int(r.volume) if r.volume is not None else None, r.currency,
                    r.exchange_tz, r.source, True) for r in df.itertuples()],
                  ['key', 'session_date', 'source'])
    a = pd.read_parquet(os.path.join(hist, 'corporate_actions.parquet'))
    a = a.drop_duplicates(['key', 'action_date', 'kind']).astype(object).where(lambda x: pd.notnull(x), None)
    n += db.upsert('corporate_actions',
                   ['key', 'action_date', 'kind', 'value', 'currency'],
                   [(r.key, r.action_date, r.kind, r.value, r.currency)
                    for r in a.itertuples()], ['key', 'action_date', 'kind'])
    return n


def load_features(db):
    d = json.load(open(os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')))
    snap = d['generated']
    n = db.upsert('app_payload', ['snapshot_date', 'payload'],
                  [(snap, json.dumps(d))], ['snapshot_date'])
    n += db.upsert('feat_screener',
                   ['snapshot_date', 'key', 'payload', 'classification',
                    'prem_disc_vs_peers_pct', 'prem_disc_vs_sector_pct', 'ev_ebitda_ltm'],
                   [(snap, r['key'], json.dumps(r), r.get('classification'),
                     r.get('prem_disc_vs_peers_pct'), r.get('prem_disc_vs_sector_pct'),
                     r.get('ev_ebitda_ltm')) for r in d['screener']],
                   ['snapshot_date', 'key'])
    n += db.upsert('feat_close_rows', ['snapshot_date', 'key', 'coverage_group', 'payload'],
                   [(snap, r['key'], r['coverage_group'], json.dumps(r))
                    for r in d['close_rows']], ['snapshot_date', 'key', 'coverage_group'])
    n += db.upsert('feat_close_groups', ['snapshot_date', 'group_display', 'payload'],
                   [(snap, g['group'], json.dumps(g)) for g in d['close_groups']],
                   ['snapshot_date', 'group_display'])
    n += db.upsert('feat_scenarios', ['snapshot_date', 'key', 'scenario', 'payload'],
                   [(snap, r['key'], r['scenario'], json.dumps(r)) for r in d['scenarios']],
                   ['snapshot_date', 'key', 'scenario'])
    n += db.upsert('feat_valuation_history', ['key', 'year', 'ev_ebitda'],
                   [(r['key'], int(r['year']), f(r['ev_ebitda'])) for r in d['hist']],
                   ['key', 'year'])
    return snap, n


def detect_changes(db, snap):
    """Diff this snapshot's screener against the previous one -> events."""
    prev = db.fetchall(
        'SELECT max(snapshot_date) FROM feat_screener WHERE snapshot_date < ?'
        .replace('?', db.ph), [snap])[0][0]
    if not prev:
        return 0
    cur = {r[0]: json.loads(r[1]) for r in db.fetchall(
        f'SELECT key, payload FROM feat_screener WHERE snapshot_date = {db.ph}', [snap])}
    old = {r[0]: json.loads(r[1]) for r in db.fetchall(
        f'SELECT key, payload FROM feat_screener WHERE snapshot_date = {db.ph}', [prev])}
    events = []
    for k, c in cur.items():
        o = old.get(k)
        if not o:
            events.append((snap, k, 'new_security', 'entered the screener universe'))
            continue
        if c.get('classification') != o.get('classification'):
            events.append((snap, k, 'classification_change',
                           f"{o.get('classification')} -> {c.get('classification')}"))
        pc, po = c.get('prem_disc_vs_peers_pct'), o.get('prem_disc_vs_peers_pct')
        if pc is not None and po is not None and abs(pc - po) >= 5:
            events.append((snap, k, 'peer_discount_move',
                           f'vs peers {po:+.1f}% -> {pc:+.1f}%'))
        m1 = (json.loads if 0 else (lambda x: x))(c.get('rel_1m_pct'))
        if c.get('price') and o.get('price') and o['price'] and \
                abs(c['price'] / o['price'] - 1) >= 0.05:
            events.append((snap, k, 'large_price_move',
                           f"price {o['price']} -> {c['price']}"))
    return db.upsert('daily_change_events',
                     ['snapshot_date', 'key', 'event_type', 'detail'],
                     events, ['snapshot_date', 'key', 'event_type'])


def export_parquet(db):
    """Archive core tables to compressed Parquet (local backup layer)."""
    if db.kind != 'duckdb':
        return
    arch = os.path.join(ROOT, 'data', 'archive')
    os.makedirs(arch, exist_ok=True)
    for t in ['raw_daily_prices', 'raw_monthly_prices', 'raw_fx_rates',
              'feat_screener', 'feat_valuation_history']:
        db.execute(f"COPY {t} TO '{arch}/{t}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db-url', default=None)
    ap.add_argument('--features-only', action='store_true')
    args = ap.parse_args()
    db = connect(args.db_url)
    u = load_universe()
    if not u:
        sys.exit('coverage-pack config not loadable (PyYAML missing?)')
    total = 0
    if not args.features_only:
        total += load_reference(db, u)
        total += load_prices(db)
        total += load_quotes(db)
        total += load_fx(db)
        total += load_fundamentals(db)
        total += load_canonical(db)
    snap, n = load_features(db)
    total += n
    ev = detect_changes(db, snap)
    export_parquet(db)
    print(f'loaded snapshot {snap}: {total} rows upserted, {ev} change events')
    for t, c in sorted(db.table_counts().items()):
        if c:
            print(f'  {t:26s} {c:>8}')
    db.close()


if __name__ == '__main__':
    main()
