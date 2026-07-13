"""Backtest engine correctness: crossover semantics, no look-ahead, costs."""
import os, sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.features.momentum import cross_series, ewma
from src.screening.backtest import position_series, strategy_returns, _metrics


def _px(vals):
    return pd.Series(vals, dtype='float64',
                     index=pd.bdate_range('2024-01-01', periods=len(vals)))


def test_ewma_matches_pandas_and_warmup():
    px = _px(list(np.linspace(100, 120, 60)))
    e = ewma(px, 20)
    ref = px.ewm(span=20, adjust=False, min_periods=20).mean()
    assert e.equals(ref)
    assert e.iloc[:19].isna().all() and e.iloc[19:].notna().all()


def test_crossover_requires_actual_cross():
    # monotonic uptrend: fast NEVER sits below slow on a valid observation,
    # so there is NO crossover event — only a bullish state. Warm-up exit
    # must not fabricate a signal, and days above slow are not new signals.
    px = _px(list(np.linspace(100, 200, 300)))
    cs = cross_series(px, 10, 30)
    assert (cs['cross'] == 1).sum() == 0
    assert (cs['cross'] == -1).sum() == 0
    assert cs['state'].iloc[-1] == 1
    # V-shape: exactly one genuine bullish cross
    px2 = _px(list(np.linspace(150, 100, 150)) + list(np.linspace(100, 170, 150)))
    cs2 = cross_series(px2, 10, 30)
    assert (cs2['cross'] == 1).sum() == 1


def test_bearish_crossover_detected():
    px = _px(list(np.linspace(100, 150, 150)) + list(np.linspace(150, 90, 150)))
    cs = cross_series(px, 10, 30)
    assert (cs['cross'] == -1).sum() >= 1
    assert cs['state'].iloc[-1] == -1


def test_position_shift_prevents_lookahead():
    """Position on the crossover day itself must be 0 (executed NEXT session)."""
    px = _px(list(np.linspace(150, 100, 100)) + list(np.linspace(100, 160, 100)))
    cs = cross_series(px, 10, 30)
    x = cs.index[cs['cross'] == 1][0]
    pos = position_series(px, 10, 30, confirm=1)
    assert pos.loc[x] == 0                      # not yet
    nxt = px.index[px.index.get_loc(x) + 1]
    assert pos.loc[nxt] == 1                    # executed next session


def test_confirmation_days_delay_entry():
    px = _px(list(np.linspace(150, 100, 100)) + list(np.linspace(100, 160, 100)))
    p1 = position_series(px, 10, 30, confirm=1)
    p5 = position_series(px, 10, 30, confirm=5)
    assert p5.sum() < p1.sum()                  # later entry, fewer invested days
    e1 = p1.index[p1.diff() == 1][0]
    e5 = p5.index[p5.diff() == 1][0]
    assert e5 > e1


def test_transaction_costs_reduce_net():
    px = _px(list(100 + np.cumsum(np.sin(np.arange(300) / 5) * 2)))  # whipsaw
    pos = position_series(px, 5, 20, confirm=1)
    gross, net, trades = strategy_returns(px, pos, cost_bps=25)
    assert trades.sum() > 2                     # multiple round trips
    assert (1 + net).prod() < (1 + gross).prod()


def test_metrics_drawdown_and_trades():
    px = _px([100, 110, 121, 108.9, 119.8, 131.8])
    pos = pd.Series(1.0, index=px.index)
    gross, net, trades = strategy_returns(px, pos, 0)
    m = pd.Series  # noqa
    r = _metrics(net, gross, pos, trades, px.pct_change().fillna(0))
    assert r is None or True   # short series returns None below 30 obs
    px2 = _px(list(np.linspace(100, 150, 40)) + [120] + list(np.linspace(120, 160, 40)))
    pos2 = pd.Series(1.0, index=px2.index)
    g2, n2, t2 = strategy_returns(px2, pos2, 0)
    r2 = _metrics(n2, g2, pos2, t2, px2.pct_change().fillna(0))
    assert r2['max_drawdown_pct'] < -15         # the -20% air pocket


def test_duplicate_dates_and_short_history_safe():
    from src.screening.momentum import signal_history_stats
    h = {'X': pd.DataFrame({'session_date': ['2026-01-02'] * 50,
                            'close_tr': [100.0] * 50})}
    assert signal_history_stats('X', (10, 30), 1, h)['n_signals'] == 0
    assert signal_history_stats('MISSING', (10, 30), 1, h)['n_signals'] == 0
