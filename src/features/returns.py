"""Session-aware return calculations on the canonical daily price history.

Two horizon families, never silently interchanged (documented in
capital_goods_methodology.md):
  - session horizons ('1D','5D','21D','63D','126D','252D'): exactly N
    completed trading sessions back on this security's own calendar.
  - calendar horizons ('1M','3M','6M','12M'): same calendar date N months
    earlier, rolled back to the last valid session ON OR BEFORE that date.

price basis: 'raw' (as traded), 'split' (split-adjusted),
'tr' (total-return-adjusted; DEFAULT for momentum/relative comparisons —
dividends and special distributions are not price crashes).

ret() returns a dict: value, start_date, end_date, n_sessions, basis,
source, status ('ok' | reason) — callers can render confidence honestly.
"""
import os
from bisect import bisect_right
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HIST = os.path.join(ROOT, 'data', 'history', 'prices_daily.parquet')

BASIS_COL = {'raw': 'close_raw', 'split': 'close_split', 'tr': 'close_tr'}
SESSION_H = {'1D': 1, '5D': 5, '21D': 21, '63D': 63, '126D': 126, '252D': 252}
CALENDAR_H = {'1M': 1, '3M': 3, '6M': 6, '12M': 12}

_cache = {}


def load_history(path=HIST):
    """{key: DataFrame indexed 0..n sorted by session_date}"""
    if 'df' not in _cache:
        df = pd.read_parquet(path)
        _cache['df'] = {k: g.sort_values('session_date').reset_index(drop=True)
                        for k, g in df.groupby('key')}
    return _cache['df']


def _shift_months(d, k):
    y, m = d.year, d.month + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def ret(key, horizon, basis='tr', asof=None, min_sessions=None, hist=None):
    h = (hist or load_history()).get(key)
    col = BASIS_COL[basis]
    out = dict(value=None, start_date=None, end_date=None, n_sessions=0,
               basis=basis, source='yahoo5y', status='no_history')
    if h is None or h.empty or col not in h:
        return out
    dates = h['session_date'].tolist()
    px = h[col].tolist()
    # as-of position: last session on or before asof (default: latest)
    if asof:
        pos = bisect_right(dates, str(asof)) - 1
    else:
        pos = len(dates) - 1
    if pos < 0:
        out['status'] = 'no_session_at_asof'
        return out
    end_px, end_d = px[pos], dates[pos]

    if horizon in SESSION_H:
        n = SESSION_H[horizon]
        start_pos = pos - n
        if start_pos < 0:
            out.update(status='insufficient_history', end_date=end_d)
            return out
    elif horizon in CALENDAR_H:
        y, m, dd = map(int, end_d.split('-'))
        target = _shift_months(date(y, m, dd), -CALENDAR_H[horizon])
        start_pos = bisect_right(dates, str(target)) - 1
        if start_pos < 0 or start_pos == pos:
            out.update(status='insufficient_history', end_date=end_d)
            return out
    else:
        raise ValueError(f'unknown horizon {horizon}')

    start_px, start_d = px[start_pos], dates[start_pos]
    n_sessions = pos - start_pos
    if min_sessions and n_sessions < min_sessions:
        out.update(status='below_min_sessions', end_date=end_d,
                   start_date=start_d, n_sessions=n_sessions)
        return out
    if not start_px or pd.isna(start_px) or not end_px or pd.isna(end_px):
        out.update(status='null_price', end_date=end_d, start_date=start_d)
        return out
    out.update(value=end_px / start_px - 1.0, start_date=start_d,
               end_date=end_d, n_sessions=n_sessions, status='ok')
    return out


def ret_pct(key, horizon, basis='tr', **kw):
    r = ret(key, horizon, basis, **kw)
    return round(r['value'] * 100, 2) if r['status'] == 'ok' else None
