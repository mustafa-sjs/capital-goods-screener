"""Point-in-time (PIT) awareness layer — SEC filing dates.

For the 37 US names present in FactIQ's SEC filings table, we know exactly
WHEN each 10-Q/10-K became public (filed_date). That makes it possible to ask
"what fundamentals were knowable on date D?" without look-ahead bias — the
prerequisite for honest historical screens and backtests on the US half of
the universe.

European names have no free filing-date source in the pipeline: their
PIT status is 'unavailable' and any historical fundamental analysis stays
labelled approximate. Never silently mix the two regimes.

Source: data/raw/sec_filing_dates.json (FactIQ sec.filings, 2020->present),
mirrored to the filing_dates DB table by scripts/load_db.py.
"""
import json, os
from bisect import bisect_right

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, 'data', 'raw', 'sec_filing_dates.json')

_cache = {}


def load_filing_dates(path=PATH):
    """{key: [(period_end, filed_date, lag_days), ...] sorted by filed_date}"""
    if 'fd' not in _cache:
        d = json.load(open(path))
        out = {}
        for r in d['rows']:
            out.setdefault(r['key'], []).append(
                (r['period_end'], r['filed_date'], r['lag_days']))
        for k in out:
            out[k].sort(key=lambda t: t[1])
        _cache['fd'] = out
    return _cache['fd']


def pit_coverage():
    return sorted(load_filing_dates())


def fundamentals_asof(key, asof, fd=None):
    """The latest reported period that was PUBLIC on `asof` (YYYY-MM-DD).

    Returns dict(status, period_end, filed_date, lag_days, periods_known).
    status: 'ok' | 'no_filings_yet' | 'pit_unavailable' (non-US/uncovered).
    """
    fd = fd or load_filing_dates()
    fl = fd.get(key)
    if not fl:
        return dict(status='pit_unavailable', period_end=None, filed_date=None,
                    lag_days=None, periods_known=0)
    filed_dates = [t[1] for t in fl]
    pos = bisect_right(filed_dates, str(asof)) - 1
    if pos < 0:
        return dict(status='no_filings_yet', period_end=None, filed_date=None,
                    lag_days=None, periods_known=0)
    # among everything filed by asof, take the LATEST period end (a 10-K can
    # be filed after a later quarter's 10-Q for off-calendar filers)
    known = fl[:pos + 1]
    best = max(known, key=lambda t: t[0])
    return dict(status='ok', period_end=best[0], filed_date=best[1],
                lag_days=best[2], periods_known=len(known))


def median_filing_lag(key, fd=None):
    fd = fd or load_filing_dates()
    fl = fd.get(key)
    if not fl:
        return None
    lags = sorted(t[2] for t in fl)
    return lags[len(lags) // 2]
