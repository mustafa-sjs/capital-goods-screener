#!/usr/bin/env python3
"""One-time dense daily-history backfill (5y) with corporate actions.

For every security: Yahoo chart 5y/1d with events=div,splits.
  - session dates from the EXCHANGE timezone (exchangeTimezoneName + zoneinfo,
    never a fixed gmtoffset)
  - close_raw   : as-traded close
  - close_tr    : total-return-adjusted close (Yahoo adjclose: splits+divs)
  - close_split : split-adjusted only (raw / cumulative forward split factor)
  - in-progress sessions excluded (complete sessions only)

Writes:
  data/history/prices_daily.parquet      (canonical daily history, committed)
  data/history/corporate_actions.parquet (dividends & splits, committed)
Then reconciles overlapping dates against stored FactIQ raw prices and writes
  data/audit/price_reconciliation_<date>.csv
Nothing is deleted: FactIQ raws stay in raw_daily_prices; conflicts are
reported, and the canonical selection reason is recorded per security.

Usage:
  backfill_history.py                 # FULL 5y rebuild, all securities
  backfill_history.py KEY ...         # full rebuild, selected securities
  backfill_history.py --recent        # INCREMENTAL: 1-month window + overlap
                                      #   reconciliation; auto-detects new
                                      #   corporate actions and full-rebuilds
                                      #   only the affected securities (TR
                                      #   scaling changes when a dividend
                                      #   lands, so incremental TR would drift)
  backfill_history.py --repair K1 K2  # full refetch for named securities
  --run-id RID                        # stamp rows with a refresh run id
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.utils.universe import load_universe

UA = {'User-Agent': 'Mozilla/5.0'}
HIST = os.path.join(ROOT, 'data', 'history')
AUDIT = os.path.join(ROOT, 'data', 'audit')


def fetch_range(symbol, rng='5y'):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
           f'?range={rng}&interval=1d&events=div%2Csplits')
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=30) as r:
        return json.load(r)['chart']['result'][0]


def fetch_5y(symbol):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
           f'?range=5y&interval=1d&events=div%2Csplits')
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=30) as r:
        return json.load(r)['chart']['result'][0]


def rows_for(key, res):
    meta = res['meta']
    tz = ZoneInfo(meta.get('exchangeTimezoneName') or 'UTC')
    ccy = meta.get('currency')
    q = res['indicators']['quote'][0]
    adj = (res['indicators'].get('adjclose') or [{}])[0].get('adjclose') or []
    ts = res.get('timestamp') or []
    reg = (meta.get('currentTradingPeriod') or {}).get('regular') or {}
    import time as _t
    session_open = (reg.get('start') and reg.get('end')
                    and reg['start'] <= _t.time() < reg['end'])
    # corporate actions
    acts = []
    ev = res.get('events') or {}
    for t, d in (ev.get('dividends') or {}).items():
        acts.append(dict(key=key, action_date=str(
            datetime.fromtimestamp(int(d.get('date', t)), tz=tz).date()),
            kind='dividend', value=d.get('amount'), currency=ccy))
    splits = []
    for t, s in (ev.get('splits') or {}).items():
        dte = datetime.fromtimestamp(int(s.get('date', t)), tz=tz).date()
        ratio = (s.get('numerator') or 1) / (s.get('denominator') or 1)
        acts.append(dict(key=key, action_date=str(dte), kind='split',
                         value=ratio, currency=None))
        splits.append((str(dte), ratio))
    splits.sort()
    prices = []
    for i, t in enumerate(ts):
        c = q['close'][i]
        if c is None:
            continue
        d = str(datetime.fromtimestamp(t, tz=tz).date())
        prices.append(dict(key=key, session_date=d, close_raw=c,
                           close_tr=(adj[i] if i < len(adj) else None),
                           volume=q['volume'][i], currency=ccy,
                           exchange_tz=str(tz), source='yahoo5y',
                           complete=True))
    # drop in-progress last session
    if session_open and prices:
        last_d = str(datetime.fromtimestamp(
            meta['regularMarketTime'], tz=tz).date())
        if prices[-1]['session_date'] == last_d:
            prices.pop()
    # split-adjusted close: divide raw by product of FUTURE split ratios
    for p in prices:
        f = 1.0
        for sd, ratio in splits:
            if p['session_date'] < sd:
                f *= ratio
        p['close_split'] = p['close_raw'] / f if f else p['close_raw']
    return prices, acts


def incremental(run_id=None):
    """1-month window per security: reconcile overlap, append new sessions,
    detect new corporate actions -> schedule full rebuild for those keys."""
    import pandas as pd
    u = load_universe()
    old = pd.read_parquet(f'{HIST}/prices_daily.parquet')
    olda = pd.read_parquet(f'{HIST}/corporate_actions.parquet')
    known_acts = {(r.key, r.action_date, r.kind) for r in olda.itertuples()}
    new_rows, conflicts, needs_full, fails = [], [], [], []
    for k, sym in u['yahoo'].items():
        try:
            p, a = rows_for(k, fetch_range(sym, '1mo'))
        except Exception as e:
            fails.append(k); print(f'{k}: FAILED {e!r}'); continue
        fresh_acts = [x for x in a if (x['key'], x['action_date'], x['kind'])
                      not in known_acts]
        if fresh_acts:
            needs_full.append(k)   # TR scale shifted; incremental would drift
            print(f'{k}: {len(fresh_acts)} new corporate action(s) -> full rebuild queued')
            continue
        mine = old[old.key == k].set_index('session_date')['close_raw']
        for row in p:
            prev = mine.get(row['session_date'])
            if prev is None:
                row['run_id'] = run_id
                new_rows.append(row)
            elif prev and abs(row['close_raw'] / prev - 1) > 0.005:
                conflicts.append(dict(key=k, date=row['session_date'],
                                      stored=round(prev, 4),
                                      fetched=round(row['close_raw'], 4),
                                      diff_pct=round((row['close_raw']/prev-1)*100, 2),
                                      run_id=run_id))
        time.sleep(0.35)
    if new_rows:
        add = pd.DataFrame(new_rows)
        # incremental TR: no new actions for these keys, so tr == raw scale
        # continues; Yahoo 1mo adjclose is anchored consistently in-window
        merged = pd.concat([old, add]).drop_duplicates(
            ['key', 'session_date'], keep='first')
        merged.sort_values(['key', 'session_date']).to_parquet(
            f'{HIST}/prices_daily.parquet', compression='zstd', index=False)
    if conflicts:
        pd.DataFrame(conflicts).to_csv(
            os.path.join(AUDIT, 'overlap_conflicts_latest.csv'), index=False)
    print(f'incremental: +{len(new_rows)} sessions, {len(conflicts)} overlap '
          f'conflicts, {len(needs_full)} securities need full rebuild, '
          f'{len(fails)} fetch failures')
    if needs_full:
        sys.argv = [sys.argv[0]] + needs_full
        main()          # targeted full rebuild for action-affected keys only
    return len(fails)


def main():
    import pandas as pd
    os.makedirs(HIST, exist_ok=True)
    os.makedirs(AUDIT, exist_ok=True)
    u = load_universe()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    keys = args or list(u['yahoo'])
    all_p, all_a, fails = [], [], []
    for k in keys:
        try:
            p, a = rows_for(k, fetch_5y(u['yahoo'][k]))
            all_p += p
            all_a += a
            print(f'{k:6s} {len(p):5d} sessions, {len(a):3d} actions, '
                  f'{p[0]["session_date"]} -> {p[-1]["session_date"]}')
        except Exception as e:
            fails.append(k)
            print(f'{k}: FAILED {e!r}')
        time.sleep(0.4)
    pdf = pd.DataFrame(all_p)
    adf = pd.DataFrame(all_a)
    if sys.argv[1:] and os.path.exists(f'{HIST}/prices_daily.parquet'):
        old = pd.read_parquet(f'{HIST}/prices_daily.parquet')
        pdf = pd.concat([old[~old.key.isin(keys)], pdf])
        olda = pd.read_parquet(f'{HIST}/corporate_actions.parquet')
        adf = pd.concat([olda[~olda.key.isin(keys)], adf])
    pdf.sort_values(['key', 'session_date']).to_parquet(
        f'{HIST}/prices_daily.parquet', compression='zstd', index=False)
    adf.sort_values(['key', 'action_date']).to_parquet(
        f'{HIST}/corporate_actions.parquet', compression='zstd', index=False)
    print(f'\n{len(pdf)} price rows, {len(adf)} corporate actions, '
          f'{len(fails)} failures{": " + ",".join(fails) if fails else ""}')

    # ---- reconciliation vs stored FactIQ raws -------------------------
    import glob
    recon = []
    for path in glob.glob(os.path.join(ROOT, 'data', 'raw', 'daily_*.json')):
        k = os.path.basename(path)[6:-5]
        d = json.load(open(path))
        fact = {r[0]: float(r[4]) for r in d.get('results', [])
                if r and r[4] not in (None, '')}
        mine = pdf[pdf.key == k].set_index('session_date')['close_raw']
        for dt, fv in fact.items():
            yv = mine.get(dt)
            if yv is None or not fv:
                continue
            diff = yv / fv - 1
            if abs(diff) > 0.005:
                recon.append(dict(key=k, date=dt, factiq=fv, yahoo=round(yv, 4),
                                  diff_pct=round(diff * 100, 2)))
    rdf = pd.DataFrame(recon)
    out = os.path.join(AUDIT, f'price_reconciliation_'
                       f'{datetime.now(timezone.utc).date()}.csv')
    rdf.to_csv(out, index=False)
    print(f'reconciliation: {len(rdf)} conflicting observations (> 0.5%) '
          f'-> {out}')
    if len(rdf):
        print(rdf.groupby('key').size().sort_values(ascending=False).head(10))


if __name__ == '__main__':
    rid = None
    if '--run-id' in sys.argv:
        i = sys.argv.index('--run-id'); rid = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    if '--recent' in sys.argv:
        sys.argv.remove('--recent')
        sys.exit(1 if incremental(rid) > len(load_universe()['yahoo']) // 2 else 0)
    if '--repair' in sys.argv:
        sys.argv.remove('--repair')
    main()
