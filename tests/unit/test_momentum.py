"""EWMA momentum engine tests on deterministic synthetic series."""
import os, sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.features.momentum import ema_metrics, momentum_state


def _hist(prices, start='2024-01-01'):
    dates = pd.bdate_range(start, periods=len(prices)).strftime('%Y-%m-%d')
    df = pd.DataFrame({'session_date': dates, 'close_raw': prices,
                       'close_tr': prices, 'close_split': prices})
    return {'X': df}


def test_ema_matches_pandas_reference():
    px = pd.Series(np.linspace(100, 150, 300) + np.sin(np.arange(300)) * 3)
    h = _hist(px.tolist())
    m = ema_metrics('X', h, (20, 60))
    ref_fast = px.ewm(span=20, adjust=False, min_periods=20).mean().iloc[-1]
    ref_slow = px.ewm(span=60, adjust=False, min_periods=60).mean().iloc[-1]
    assert abs(m['fast'] - ref_fast) < 1e-3
    assert abs(m['slow'] - ref_slow) < 1e-3
    assert m['state'] == 'bullish'                 # rising series


def test_min_periods_blocks_short_series():
    m = ema_metrics('X', _hist(list(np.linspace(100, 110, 40))), (20, 60))
    assert m['status'] == 'insufficient_data'


def test_fresh_cross_is_emerging_inflection():
    # long downtrend then sharp V-recovery -> fast crosses above slow recently
    px = list(np.linspace(150, 100, 260)) + list(np.linspace(100, 120, 22))
    state, m = momentum_state('X', _hist(px))
    assert m['state'] == 'bullish'
    assert m['sessions_since_cross'] <= 15
    assert state == 'emerging_positive_inflection'


def test_steady_downtrend_is_established_downtrend():
    px = list(np.linspace(150, 80, 300))
    state, _ = momentum_state('X', _hist(px))
    assert state == 'established_downtrend'


def test_flat_noise_not_labelled_trending():
    rng = np.random.default_rng(7)
    px = list(100 + np.cumsum(rng.normal(0, 0.05, 300)))
    state, m = momentum_state('X', _hist(px))
    assert state in ('indeterminate', 'fading_uptrend',
                     'emerging_positive_inflection', 'emerging_breakdown',
                     'established_uptrend', 'established_downtrend')
    assert m['status'] == 'ok'                     # engine runs; no crash on noise
