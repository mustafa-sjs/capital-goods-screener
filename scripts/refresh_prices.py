#!/usr/bin/env python3
"""Incremental price refresh for the Capital Goods dashboard.

Pulls current quotes + the last month of daily closes from Yahoo Finance's
public chart endpoint (no API key) and merges them into the existing
data/raw/quote_KEY.json and daily_KEY.json payloads, preserving the FactIQ
file format the engine reads. FX pairs refresh the same way. FactIQ remains
the source of record for fundamentals, statements, monthly history and deep
price history — this only tops up the recent end.

Usage:
    python3 scripts/refresh_prices.py            # refresh everything
    python3 scripts/refresh_prices.py ABBN SU    # refresh selected keys
Then re-run the engine and re-assemble:
    python3 scripts/compute_metrics.py
    python3 <build_viz.py> assemble --template scripts/dashboard_template.html \
        --data dash=data/computed/dashboard_data.json --out capital_goods_dashboard.html

Bars whose regular session has not yet closed are used for the live quote but
NOT merged into the daily series (they would be provisional closes).
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data', 'raw')
UA = {'User-Agent': 'Mozilla/5.0'}

# FactIQ key -> Yahoo symbol (same listing line & quote currency as the stored
# payloads; Nordics use native OMX lines, which quote in the same SEK/EUR as
# the LSE international order-book lines used for history).
YAHOO = {
    # Europe
    'ABBN': 'ABBN.SW', 'SRAIL': 'SRAIL.SW', 'SCHP': 'SCHP.SW',
    'ALO': 'ALO.PA', 'LR': 'LR.PA', 'NEX': 'NEX.PA', 'RXL': 'RXL.PA', 'SU': 'SU.PA',
    'PRY': 'PRY.MI',
    'SIE': 'SIE.DE', 'DTG': 'DTG.DE', '8TRA': '8TRA.DE',
    'VOLVB': 'VOLV-B.ST', 'ASSAB': 'ASSA-B.ST', 'ATCOA': 'ATCO-A.ST',
    'EPIA': 'EPI-A.ST', 'SAND': 'SAND.ST', 'SKFB': 'SKF-B.ST',
    'KNEBV': 'KNEBV.HE', 'METSO': 'METSO.HE',
    'HLMA': 'HLMA.L', 'IMI': 'IMI.L', 'ROR': 'ROR.L', 'SMIN': 'SMIN.L',
    'SPX': 'SPX.L', 'WEIR': 'WEIR.L', 'RR': 'RR.L', 'MRO': 'MRO.L',
    # Japan
    'NSK': '6471.T', 'NTN': '6472.T', 'EBARA': '6361.T',
    # US (plain tickers except Moog class A)
    'MOGA': 'MOG-A',
}
US_PLAIN = ['PCAR','OTIS','ETN','ROK','GE','EMR','WAB','GBX','TT','ATKR','BDC',
            'VISN','GLW','FAST','WCC','VRT','HON','JCI','CMI','OSK','DE','CARR',
            'COHR','FN','LITE','AME','WTS','BMI','FLS','CR','ITT','LII','DHR',
            'IR','IEX','KMT','CAT','TEX','ALLE','AMAT','KLAC','TKR','RTX','HWM',
            'TDG','WWD','HXL']
for k in US_PLAIN: YAHOO[k] = k

# config override: the coverage-pack YAML is the source of truth when available
try:
    import sys as _sys
    _sys.path.insert(0, ROOT)
    from src.utils.universe import load_universe as _lu
    _u = _lu()
    if _u and _u.get('yahoo'):
        YAHOO = _u['yahoo']
except Exception:
    pass

FX_PAIRS = ['CHFUSD', 'EURUSD', 'GBPUSD', 'JPYUSD', 'SEKUSD']


def fetch(symbol, rng='1mo'):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
           f'?range={rng}&interval=1d')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.load(r)
    res = payload['chart']['result'][0]
    meta = res['meta']
    ts = res.get('timestamp') or []
    quote = res['indicators']['quote'][0]
    gmtoff = meta.get('gmtoffset', 0)
    bars = []
    for i, t in enumerate(ts):
        c = quote['close'][i]
        if c is None: continue
        d = datetime.fromtimestamp(t + gmtoff, tz=timezone.utc).strftime('%Y-%m-%d')
        bars.append(dict(date=d, open=quote['open'][i], high=quote['high'][i],
                         low=quote['low'][i], close=c, volume=quote['volume'][i]))
    # collapse duplicate dates (Yahoo sometimes appends a live bar for the
    # same session) keeping the last occurrence
    dedup = {}
    for b in bars: dedup[b['date']] = b
    bars = sorted(dedup.values(), key=lambda b: b['date'])
    # session-complete guard: drop today's bar from the *series* if the
    # regular session hasn't ended yet (still used for the live quote)
    reg = (meta.get('currentTradingPeriod') or {}).get('regular') or {}
    import time as _t
    session_open = (reg.get('start') and reg.get('end')
                    and reg['start'] <= _t.time() < reg['end'])
    complete = bars[:-1] if (session_open and bars) else bars
    return meta, bars, complete


def s(v, dp=5):
    return None if v is None else f'{v:.{dp}f}'


def refresh_key(k):
    sym = YAHOO[k]
    meta, bars, complete = fetch(sym)
    qpath = os.path.join(RAW, f'quote_{k}.json')
    dpath = os.path.join(RAW, f'daily_{k}.json')
    q = json.load(open(qpath))
    cols = q['columns']
    row = dict(zip(cols, q['results'][0]))
    old_close, old_dt = row.get('close'), row.get('datetime')

    px = meta.get('regularMarketPrice')
    dt = datetime.fromtimestamp(meta['regularMarketTime'] + meta.get('gmtoffset', 0),
                                tz=timezone.utc).strftime('%Y-%m-%d')
    # previous close = the last completed bar strictly before the quote date
    # (meta.chartPreviousClose is the close before the RANGE start — wrong)
    older = [b for b in bars if b['date'] < dt]
    prev = older[-1]['close'] if older else None
    ccy = meta.get('currency')
    stored_ccy = q.get('currency')
    if ccy and stored_ccy and ccy != stored_ccy:
        return f'{k}: CCY MISMATCH yahoo={ccy} stored={stored_ccy} — skipped'

    last = bars[-1] if bars else {}
    row.update({'close': s(px), 'previous_close': s(prev), 'datetime': dt,
                'timestamp': meta['regularMarketTime'],
                'last_quote_at': meta['regularMarketTime'],
                'open': s(last.get('open')), 'high': s(last.get('high')),
                'low': s(last.get('low')),
                'volume': str(last.get('volume') or ''),
                'change': s(px - prev if px and prev else None),
                'percent_change': s((px / prev - 1) * 100 if px and prev else None),
                'is_market_open': False})
    hi, lo = meta.get('fiftyTwoWeekHigh'), meta.get('fiftyTwoWeekLow')
    if hi and lo and px:
        row.update({'fifty_two_week.low': s(lo), 'fifty_two_week.high': s(hi),
                    'fifty_two_week.low_change': s(px - lo),
                    'fifty_two_week.high_change': s(px - hi),
                    'fifty_two_week.low_change_percent': s((px / lo - 1) * 100),
                    'fifty_two_week.high_change_percent': s((px / hi - 1) * 100),
                    'fifty_two_week.range': f'{s(lo)} - {s(hi)}'})
    q['results'][0] = [row.get(c) for c in cols]
    q['refresh_source'] = 'Yahoo Finance chart endpoint (secondary live source)'
    q['refreshed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    json.dump(q, open(qpath, 'w'))

    # merge completed daily bars (results are newest-first rows of
    # [date, open, high, low, close, volume])
    added = 0
    if os.path.exists(dpath):
        d = json.load(open(dpath))
        have = {r[0] for r in d['results']}
        new_rows = [[b['date'], s(b['open']), s(b['high']), s(b['low']),
                     s(b['close']), str(b['volume'] or '')]
                    for b in complete if b['date'] not in have]
        if new_rows:
            d['results'] = sorted(d['results'] + new_rows,
                                  key=lambda r: r[0], reverse=True)
            d['row_count'] = len(d['results'])
            d['refresh_source'] = 'Yahoo Finance chart endpoint (recent bars merged)'
            json.dump(d, open(dpath, 'w'))
            added = len(new_rows)
    return (f'{k:6s} {old_dt} {old_close} -> {dt} {s(px)} {ccy}'
            f'  (+{added} daily bars)')


def refresh_fx(pair):
    meta, bars, complete = fetch(pair + '=X', rng='5d')
    path = os.path.join(RAW, f'fx_{pair}.json')
    d = json.load(open(path))
    have = {r[0] for r in d['results']}
    new_rows = [[b['date'], s(b['open']), s(b['high']), s(b['low']), s(b['close'])]
                for b in complete if b['date'] not in have]
    # always update the newest stored row's close to the latest rate
    if bars:
        latest = bars[-1]
        for r in d['results']:
            if r[0] == latest['date']:
                r[4] = s(latest['close'])
    if new_rows:
        d['results'] = sorted(d['results'] + new_rows,
                              key=lambda r: r[0], reverse=True)
        d['row_count'] = len(d['results'])
    d['refresh_source'] = 'Yahoo Finance chart endpoint'
    json.dump(d, open(path, 'w'))
    return f'fx {pair}: newest {d["results"][0][0]} {d["results"][0][4]} (+{len(new_rows)} rows)'


if __name__ == '__main__':
    keys = sys.argv[1:] or list(YAHOO)
    fails = []
    for k in keys:
        if k not in YAHOO:
            print(f'{k}: unknown key'); continue
        try:
            print(refresh_key(k))
        except Exception as e:
            fails.append(k); print(f'{k}: FAILED {e!r}')
        time.sleep(0.35)
    for p in FX_PAIRS:
        try:
            print(refresh_fx(p))
        except Exception as e:
            fails.append('fx_' + p); print(f'fx {p}: FAILED {e!r}')
        time.sleep(0.35)
    print(f'\ndone: {len(keys) + len(FX_PAIRS) - len(fails)} refreshed, '
          f'{len(fails)} failed{": " + ", ".join(fails) if fails else ""}')
