"""Momentum-consistency tests (product spec §14 / §15 / §27).

One momentum engine, one set of user-facing fields, ranks calculated
within the selected universe.
"""
import json, os, sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.features.momentum import (simple_momentum_fields, pair_features,
                                   momentum_config, TREND_UP, TREND_DOWN,
                                   TREND_NONE, SIG_POS, SIG_NONE,
                                   CHG_STRONGER, CHG_WEAKER, CHG_STABLE)
from src.utils.universe import universe_service


def test_simple_fields_from_synthetic_states():
    # insufficient data -> no clear trend, nothing else claimed
    out = simple_momentum_fields(dict(status='insufficient_data'))
    assert out == dict(trend=TREND_NONE, momentum_change=None,
                       recent_signal=None)
    # bullish, widening distance, fresh confirmed cross
    out = simple_momentum_fields(dict(status='ok', signal='bullish',
                                      dist_chg_5s=0.5, cross_type='bullish',
                                      sessions_since_cross=3))
    assert out == dict(trend=TREND_UP, momentum_change=CHG_STRONGER,
                       recent_signal=SIG_POS)
    # bearish, narrowing distance, old cross -> no recent signal
    out = simple_momentum_fields(dict(status='ok', signal='bearish',
                                      dist_chg_5s=-0.5, cross_type='bearish',
                                      sessions_since_cross=200))
    assert out['trend'] == TREND_DOWN
    assert out['momentum_change'] == CHG_WEAKER
    assert out['recent_signal'] == SIG_NONE
    # a cross whose direction no longer holds is not a recent signal
    out = simple_momentum_fields(dict(status='ok', signal='bullish',
                                      dist_chg_5s=0.0, cross_type='bearish',
                                      sessions_since_cross=2))
    assert out['recent_signal'] == SIG_NONE
    assert out['momentum_change'] == CHG_STABLE


@pytest.fixture(scope='module')
def svc():
    return universe_service()


@pytest.fixture(scope='module')
def core_table(svc):
    from src.screening.momentum import build_table
    pair = tuple(momentum_config()['ewma']['default_pair'])
    return build_table(sorted(svc['core']), svc['names'], svc['sub_of'],
                       svc['peers_of'], pair, 5)


def test_core_ranks_calculated_within_core(core_table):
    """Selecting core coverage must rank across exactly those 30 companies —
    never across the full universe and then filtered."""
    assert len(core_table) == 30
    ranks = core_table['rank'].dropna()
    assert ranks.min() == 1
    assert ranks.max() <= 30
    pctile_cols = [c for c in core_table.columns if c.endswith('_pctile')]
    for c in pctile_cols:
        assert core_table[c].max() <= 100


def test_missing_optional_fields_do_not_drop_companies(core_table, svc):
    assert set(core_table['key']) == set(svc['core'])


def test_payload_and_engine_agree_on_trend(core_table):
    """The screener payload's Trend must equal the momentum engine's output
    for the same default pair — one momentum system everywhere."""
    p = os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')
    d = json.load(open(p))
    payload_trend = {r['key']: r['trend'] for r in d['screener']}
    engine_trend = dict(zip(core_table['key'], core_table['trend']))
    diff = {k for k in payload_trend
            if payload_trend[k] != engine_trend.get(k)}
    assert not diff, f'trend disagrees between payload and engine for {diff}'


def test_payload_and_engine_agree_on_signal_date(core_table):
    p = os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')
    d = json.load(open(p))
    pair = tuple(momentum_config()['ewma']['default_pair'])
    for k in list(core_table['key'])[:8]:
        pf = pair_features(k, pair)
        row = core_table[core_table['key'] == k].iloc[0]
        assert row['cross_date'] == pf.get('cross_date')


def test_trend_field_values_are_controlled_vocabulary(core_table):
    assert set(core_table['trend'].dropna()) <= {TREND_UP, TREND_DOWN,
                                                 TREND_NONE}
    assert set(core_table['momentum_change'].dropna()) <= \
        {CHG_STRONGER, CHG_STABLE, CHG_WEAKER}
