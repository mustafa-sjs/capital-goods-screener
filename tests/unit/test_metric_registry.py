"""Metric-label tests (product spec §6 / §27): default tables resolve
through the central registry and no raw internal column name leaks into
the default user interface."""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.utils import metrics as M

# raw internal names that must never appear as a user-facing label
FORBIDDEN_LABELS = {'rel_3m', 'rel_3m_pct', 'drawdown_52w_pct', 'hist_zscore',
                    'prem_disc_vs_peers_pct', 'ev_ebitda_ltm', 'c5', 'OOS',
                    'ρ30', 'corr-wtd', 'β-adj', 'Hist z', 'Dmargin pp'}


def test_registry_entries_complete():
    for mid, d in M.METRIC_DEFINITIONS.items():
        assert d['display_name'], mid
        assert d['description'], mid
        assert d['format'], mid
        assert d['category'], mid
        assert d['higher_means'] in ('better', 'worse', 'more_expensive',
                                     'cheaper', 'neutral'), mid


def test_display_names_are_plain_english():
    for mid, d in M.METRIC_DEFINITIONS.items():
        for label in (d['display_name'], d['short_name']):
            assert label not in FORBIDDEN_LABELS, label
            assert '_' not in label, f'{mid}: label "{label}" looks internal'


def test_default_screener_columns_all_registered():
    """Every metric id the screener page shows by default must resolve
    through the registry (freshness is page-local and labelled there)."""
    src = open(os.path.join(ROOT, 'app', 'views', 'screener.py')).read()
    m = re.search(r'TAB_COLS = \{(.+?)\n\}', src, re.S)
    assert m, 'TAB_COLS not found in screener.py'
    ids = re.findall(r"'([a-z0-9_]+)'", m.group(1))
    page_local = {'overview', 'valuation', 'fundamentals', 'risk', 'company',
                  'freshness'}
    for mid in ids:
        if mid in page_local:
            continue
        assert mid in M.METRIC_DEFINITIONS, f'unregistered default column {mid}'


def test_table_spec_round_trip():
    rename, style_kw, help_map = M.table_spec(
        ['company', 'ev_ebitda_ltm', 'prem_disc_vs_peers_pct',
         'rev_growth_pct', 'nd_ebitda', 'trend'])
    assert rename['ev_ebitda_ltm'] == 'EV/EBITDA'
    assert rename['prem_disc_vs_peers_pct'] == 'vs direct peers'
    assert 'vs direct peers' in style_kw['pct_cols']
    assert 'EV/EBITDA' in style_kw['mult_cols']
    assert help_map['EV/EBITDA']
    # unregistered ids fall back to themselves (visible, and caught here)
    r2, _, _ = M.table_spec(['company', 'no_such_metric'])
    assert r2['no_such_metric'] == 'no_such_metric'


def test_same_metric_described_once():
    """One definition per metric — the same display name must not be reused
    for two different internal ids with different descriptions."""
    seen = {}
    for mid, d in M.METRIC_DEFINITIONS.items():
        key = d['display_name']
        if key in seen:
            assert d['description'] == seen[key], \
                f'{key} described differently for {mid}'
        seen[key] = d['description']
