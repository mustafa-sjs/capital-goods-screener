"""Session-aware return function tests: synthetic calendars + the real
ABBN/Legrand regression cases from the 2026-07 price-data audit."""
import os, sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.features.returns import ret, load_history


def _hist(rows):
    df = pd.DataFrame(rows, columns=['session_date', 'close_raw'])
    df['close_split'] = df['close_raw']
    df['close_tr'] = df['close_raw']
    return {'X': df}


# synthetic calendar: Fri 2026-01-02, holiday Mon 01-05 missing, then Tue-Fri
SYN = _hist([('2026-01-02', 100.0), ('2026-01-06', 102.0), ('2026-01-07', 101.0),
             ('2026-01-08', 104.0), ('2026-01-09', 106.0), ('2026-02-06', 110.0),
             ('2026-02-09', 112.0)])


def test_1d_skips_weekend_and_holiday():
    r = ret('X', '1D', 'raw', asof='2026-01-06', hist=SYN)
    assert r['status'] == 'ok'
    assert r['start_date'] == '2026-01-02'      # Fri -> Tue over holiday Monday
    assert abs(r['value'] - 0.02) < 1e-12


def test_session_horizon_counts_exact_sessions():
    r = ret('X', '5D', 'raw', asof='2026-02-06', hist=SYN)
    assert r['n_sessions'] == 5 and r['start_date'] == '2026-01-02'


def test_calendar_month_rolls_back_to_prior_session():
    # 1M back from 2026-02-09 = 2026-01-09 (a valid session)
    r = ret('X', '1M', 'raw', asof='2026-02-09', hist=SYN)
    assert r['start_date'] == '2026-01-09'
    assert abs(r['value'] - (112.0 / 106.0 - 1)) < 1e-12
    # 1M back from 2026-02-06 = 2026-01-06
    r = ret('X', '1M', 'raw', asof='2026-02-06', hist=SYN)
    assert r['start_date'] == '2026-01-06'


def test_insufficient_history_flagged_not_faked():
    r = ret('X', '252D', 'raw', hist=SYN)
    assert r['status'] == 'insufficient_history' and r['value'] is None


def test_duplicate_dates_impossible_after_load():
    h = load_history()
    for k in ('ABBN', 'MRO', 'VISN'):
        d = h[k]['session_date']
        assert d.is_unique, f'{k} has duplicate sessions'
        assert (d.sort_values().values == d.values).all(), f'{k} not sorted'


# ---- real-data regression: values must ARISE from the functions ----------
@pytest.mark.parametrize('key,h,expected,tol', [
    ('ABBN', '1M', 5.00, 0.35), ('ABBN', '3M', 16.34, 0.35),
    ('LR', '1M', 3.15, 0.35), ('LR', '3M', -5.48, 0.35)])
def test_audit_regression(key, h, expected, tol):
    r = ret(key, h, 'raw', asof='2026-07-10')
    assert r['status'] == 'ok'
    assert abs(r['value'] * 100 - expected) < tol, \
        f'{key} {h}: {r["value"]*100:.2f} vs {expected} ({r["start_date"]})'


def test_gbp_pence_series_consistent():
    h = load_history()['MRO']
    assert h['currency'].iloc[-1] == 'GBp'
    assert h['close_raw'].iloc[-1] > 100          # pence magnitude, not pounds


def test_visn_special_distribution_handled():
    """Raw shows the mechanical fall; total return must not treat the $10
    special distribution as a ~-49% crash."""
    raw = ret('VISN', '1D', 'raw', asof='2026-04-28')
    tr = ret('VISN', '1D', 'tr', asof='2026-04-28')
    assert raw['value'] < -0.40                    # mechanical ex-date fall
    assert tr['value'] > -0.20                     # economically much smaller
    acts = pd.read_parquet(os.path.join(ROOT, 'data', 'history',
                                        'corporate_actions.parquet'))
    v = acts[(acts.key == 'VISN') & (acts.kind == 'dividend')]
    assert len(v) and abs(v['value'].max() - 10.0) < 0.01
