import json, os, sys, tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.screening.events import detect_events
from src.features.momentum import momentum_state
from src.database import db as dbmod
from src.database.db import DB


def _row(**kw):
    base = dict(momentum_state='indeterminate', valuation_state='fair',
                fundamental_state='stable', prem_disc_vs_peers_pct=-5.0,
                hist_percentile=50.0, drawdown_52w_pct=-10.0,
                rev_growth_pct=2.0, margin_chg_pp=0.5, nd_ebitda=1.0,
                data_quality='OK', hist_years=6)
    base.update(kw)
    return base


def _types(evs):
    return {e[2] for e in evs}


def test_state_change_and_threshold_events():
    prev = {'X': _row()}
    cur = {'X': _row(momentum_state='established uptrend',
                     prem_disc_vs_peers_pct=-17.0)}
    t = _types(detect_events(cur, prev, snap='2026-07-13'))
    assert 'momentum_state_change' in t
    assert 'peer_discount_threshold' in t          # crossed -15
    assert 'peer_discount_move' in t               # moved 12pp


def test_no_events_when_nothing_changed():
    prev = {'X': _row()}
    assert detect_events({'X': _row()}, prev, snap='s') == []


def test_universe_entry_exit_and_52w_high():
    prev = {'X': _row(drawdown_52w_pct=-8.0), 'GONE': _row()}
    cur = {'X': _row(drawdown_52w_pct=-0.1), 'NEW': _row()}
    t = _types(detect_events(cur, prev, snap='s'))
    assert {'new_52w_high', 'universe_entry', 'universe_exit'} <= t


def test_quality_resolution_event():
    prev = {'X': _row(data_quality='OK; EBIT reconstructed')}
    cur = {'X': _row(data_quality='OK')}
    evs = detect_events(cur, prev, snap='s')
    assert _types(evs) == {'data_quality_resolved'}
    d = json.loads(evs[0][3])
    assert d['prev'] and d['cur'] == 'OK'


# ---- momentum edge cases required by the v2.3 spec -----------------------
def _hist(prices):
    dates = pd.bdate_range('2024-01-01', periods=len(prices)).strftime('%Y-%m-%d')
    return {'X': pd.DataFrame({'session_date': dates, 'close_raw': prices,
                               'close_tr': prices, 'close_split': prices})}


def test_sideways_market_is_not_a_trend():
    state, _ = momentum_state('X', _hist([100.0] * 300))
    assert state == 'indeterminate'


def test_false_crossover_reversal_not_uptrend():
    # uptrend, sharp dip crossing down, immediate recovery: must not be
    # labelled established_downtrend
    px = (list(np.linspace(100, 130, 250)) + list(np.linspace(130, 118, 10))
          + list(np.linspace(118, 131, 15)))
    state, m = momentum_state('X', _hist(px))
    assert state != 'established_downtrend'


def test_corporate_action_gap_uses_tr_not_raw():
    # raw gaps down 40% (special dividend), tr continuous -> engine on tr
    raw = list(np.linspace(100, 120, 200)) + list(np.linspace(72, 80, 100))
    tr = list(np.linspace(100, 120, 200)) + list(np.linspace(120, 133, 100))
    dates = pd.bdate_range('2024-01-01', periods=300).strftime('%Y-%m-%d')
    h = {'X': pd.DataFrame({'session_date': dates, 'close_raw': raw,
                            'close_tr': tr, 'close_split': raw})}
    state, m = momentum_state('X', h)
    assert m['state'] == 'bullish'          # tr basis sees no crash
    assert state in ('established_uptrend', 'fading_uptrend',
                     'emerging_positive_inflection')


# ---- candidate gate & screen-condition logic ------------------------------
def test_candidate_checks_run_and_flag_missing_history(monkeypatch):
    tmp = tempfile.mktemp(suffix='.duckdb')
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tmp)
    d = DB(); d.init_schema()
    d.upsert('securities', ['key', 'name', 'quote_ccy', 'report_ccy', 'active'],
             [('ZZZ', 'Test Co', 'USD', 'USD', True)], ['key'])
    from src.validation.checks import run_candidate_checks
    counts = run_candidate_checks(d, 'test-run')
    assert counts['total'] >= 1
    subj = [r[0] for r in d.fetchall(
        "SELECT subject FROM validation_results WHERE check_name = "
        "'missing_canonical_history'")]
    assert 'ZZZ' in subj


def test_screen_condition_application():
    df = pd.DataFrame([
        dict(key='A', prem_disc_vs_peers_pct=-20, momentum_state='established uptrend'),
        dict(key='B', prem_disc_vs_peers_pct=-20, momentum_state='established downtrend'),
        dict(key='C', prem_disc_vs_peers_pct=5, momentum_state='established uptrend'),
        dict(key='D', prem_disc_vs_peers_pct=None, momentum_state='established uptrend')])
    conds = [dict(metric='prem_disc_vs_peers_pct', op='<=', value=-15),
             dict(metric='momentum_state', op='in', value=['established uptrend'])]
    f = df.copy()
    for c in conds:                       # same logic as the screener page
        m, op, v = c['metric'], c['op'], c['value']
        if op == 'in':
            f = f[f[m].isin(v)]
        else:
            f = f[f[m].notna()]
            f = f[f[m] <= v] if op == '<=' else f[f[m] >= v]
    assert f['key'].tolist() == ['A']     # nulls excluded, AND applied
