"""Universe-consistency tests (product spec §13 / §27).

The shared universe service is the ONLY source of coverage membership;
these tests pin the invariants every page relies on.
"""
import os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.utils.universe import (universe_service, universe_keys,
                                validate_universe, UNIVERSE_OPTIONS,
                                DEFAULT_UNIVERSE, EXPECTED_CORE_COUNT)


@pytest.fixture(scope='module')
def svc():
    return universe_service()


def test_exactly_30_core_companies(svc):
    assert len(svc['core']) == EXPECTED_CORE_COUNT == 30
    assert len(set(svc['core'])) == 30


def test_siemens_and_schneider_present(svc):
    assert 'SIE' in svc['core'], 'Siemens must be in core coverage'
    assert 'SU' in svc['core'], 'Schneider Electric must be in core coverage'
    assert 'ABBN' in svc['core'] and 'LR' in svc['core']


def test_one_primary_listing_per_core_company(svc):
    names = [svc['names'][k] for k in svc['core']]
    assert len(names) == len(set(names)), 'duplicate primary listings'
    for k in svc['core']:
        assert svc['tickers'][k], f'{k} has no display ticker'


def test_one_subgroup_per_core_company(svc):
    for k in svc['core']:
        assert svc['sub_of'].get(k), f'{k} has no subgroup'
    assert len({svc['sub_of'][k] for k in svc['core']}) == 5


def test_every_core_company_has_a_peer_basket(svc):
    for k in svc['core']:
        assert svc['peers_of'].get(k), f'{k} has no direct-peer basket'


def test_universe_selector_shapes(svc):
    core = universe_keys('Core coverage', svc)
    both = universe_keys('Core coverage + direct peers', svc)
    full = universe_keys('Full universe', svc)
    assert len(core) == 30
    assert set(core) <= set(both) <= set(full)
    assert set(full) == set(svc['all'])
    assert DEFAULT_UNIVERSE == 'Core coverage'
    assert DEFAULT_UNIVERSE in UNIVERSE_OPTIONS


def test_validation_catches_missing_core_company(svc):
    broken = dict(svc)
    broken['core'] = [k for k in svc['core'] if k != 'SIE']
    problems = validate_universe(broken)
    assert any('SIE' in p for p in problems)
    assert any('29' in p for p in problems)


def test_payload_universe_matches_service(svc):
    """The engine payload's screener rows must be exactly the core set."""
    import json
    p = os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')
    d = json.load(open(p))
    payload_keys = {r['key'] for r in d['screener']}
    assert payload_keys == set(svc['core'])
    # subgroup names identical between config and payload
    for r in d['screener']:
        assert r['subgroup'] == svc['sub_of'][r['key']]
