"""Page-integrity tests (product spec §27): every page loads without an
exception against the real local data, and price/universe figures agree
across pages."""
import json, os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'app'))

PAGES = ['home.py', 'screener.py', 'compare.py', 'company.py',
         'market_close.py', 'watchlists.py', 'admin.py', 'methodology.py',
         'full_dashboard.py']


@pytest.mark.parametrize('page', PAGES)
def test_page_loads_without_exception(page):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, 'app', 'views', page),
                           default_timeout=180)
    at.run()
    errs = [e.value for e in at.exception]
    assert not errs, f'{page}: {errs[0]}'


def test_navigation_registers_all_pages():
    src = open(os.path.join(ROOT, 'app', 'Home.py')).read()
    for page in PAGES:
        assert f'views/{page}' in src, f'{page} missing from navigation'
    for title in ('Overview', 'Stock Screener', 'Compare Companies',
                  'Company Analysis', 'Market & Peers', 'Watchlists',
                  'Data Status', 'Methodology', 'Legacy Dashboard'):
        assert title in src


def test_same_price_across_screener_and_scenarios():
    """One current price per company across payload consumers."""
    d = json.load(open(os.path.join(ROOT, 'data', 'computed',
                                    'dashboard_data.json')))
    px_screener = {r['key']: r['price'] for r in d['screener']}
    for s in d['scenarios']:
        if s['key'] in px_screener and s.get('current_price') is not None:
            assert abs(s['current_price'] - px_screener[s['key']]) < 1e-6, \
                f"{s['key']}: scenario price differs from screener price"
    # close_rows for coverage must carry the same close
    for r in d['close_rows']:
        if r['role'] == 'coverage' and r['key'] in px_screener \
                and r.get('close_px') is not None \
                and px_screener[r['key']] is not None:
            assert abs(r['close_px'] - px_screener[r['key']]) < 1e-6, \
                f"{r['key']}: market-close price differs from screener price"


def test_no_raw_json_or_snapshot_ids_on_overview():
    src = open(os.path.join(ROOT, 'app', 'views', 'home.py')).read()
    assert 'st.json' not in src
    assert 'What changed since the previous snapshot' not in src
    assert 'No change events vs the previous snapshot' not in src
    # the replacement plain-English copy is present
    assert 'No material changes since the previous market update.' in src
