"""Invariants of the committed engine snapshot — these compare the live
payload against independently recomputed values (the same spot-checks the
original dashboard QA performed by hand)."""
import json, os, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = json.load(open(os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')))


def test_uniform_estimate_basis():
    bases = {r['estimate_basis'] for r in D['screener']}
    assert bases == {'LTM reported fallback'}, 'NTM/LTM mixing is forbidden'


def test_peer_premium_consistency():
    for r in D['screener']:
        if r['prem_disc_vs_peers_pct'] is None or not r['peer_median_ev_ebitda']:
            continue
        implied = (r['ev_ebitda_ltm'] / r['peer_median_ev_ebitda'] - 1) * 100
        assert abs(implied - r['prem_disc_vs_peers_pct']) < 1.0, r['key']


def test_basket_stats_recompute():
    by_key = {}
    for row in D['close_rows']:
        by_key.setdefault(row['key'], row)
    for g in D['close_groups']:
        moves = [by_key[p]['move_1d_pct'] for p in g['peers']
                 if p in by_key and by_key[p].get('move_1d_pct') is not None]
        if not moves:
            continue
        assert abs(st.mean(moves) - g['stats']['eq']) < 0.02, g['group']
        assert abs(st.median(moves) - g['stats']['median']) < 0.02, g['group']


def test_scenario_bridges_additive():
    for row in D['scenarios']:
        ret = row['implied_return_pct']
        if ret is None:
            continue
        s = (row['earnings_effect_pct'] or 0) + (row['multiple_effect_pct'] or 0)
        assert abs(ret - s) < 0.2, f"{row['key']} {row['scenario']}"


def test_sector_dedup():
    keys = [r['key'] for r in D['screener']]
    assert len(keys) == len(set(keys)), 'duplicate coverage rows'


def test_no_zero_filled_multiples():
    for r in D['screener']:
        for c in ('ev_ebitda_ltm', 'ev_ebit_ltm', 'pe_ltm'):
            assert r[c] != 0, f"{r['key']}.{c} zero-filled (must be null/NM)"
