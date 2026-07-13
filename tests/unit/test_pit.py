"""Point-in-time layer tests — the no-look-ahead guarantees."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.features.pit import (fundamentals_asof, load_filing_dates,
                              median_filing_lag, pit_coverage)

FD = {'TESTCO': [('2025-12-31', '2026-02-14', 45),
                 ('2026-03-31', '2026-05-05', 35)]}


def test_asof_before_first_filing_knows_nothing():
    r = fundamentals_asof('TESTCO', '2026-02-13', FD)
    assert r['status'] == 'no_filings_yet' and r['period_end'] is None


def test_asof_on_filing_date_knows_the_period():
    r = fundamentals_asof('TESTCO', '2026-02-14', FD)
    assert r['status'] == 'ok' and r['period_end'] == '2025-12-31'


def test_asof_between_filings_does_not_see_future_quarter():
    """THE look-ahead test: on 2026-05-04, Q1 results exist in the database
    but were not yet public — PIT must return the December period."""
    r = fundamentals_asof('TESTCO', '2026-05-04', FD)
    assert r['period_end'] == '2025-12-31'
    r2 = fundamentals_asof('TESTCO', '2026-05-05', FD)
    assert r2['period_end'] == '2026-03-31'


def test_uncovered_name_is_labelled_not_guessed():
    r = fundamentals_asof('SIE', '2026-05-04', FD)
    assert r['status'] == 'pit_unavailable'


def test_real_payload_loads_with_expected_coverage():
    fd = load_filing_dates()
    cov = pit_coverage()
    assert len(cov) == 37
    assert 'ETN' in cov and 'CAT' in cov
    assert 'SIE' not in cov and 'VISN' not in cov      # documented gaps
    # every filing strictly after its period end, with sane lags
    for k, fl in fd.items():
        for period, filed, lag in fl:
            assert filed > period, f'{k} {period} filed before period end?'
            assert 10 <= lag <= 120, f'{k} {period} implausible lag {lag}'
    assert 20 <= median_filing_lag('ETN') <= 60
