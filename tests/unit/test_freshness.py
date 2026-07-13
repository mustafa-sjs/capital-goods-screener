"""v2.6 freshness pipeline tests — mocked Yahoo, retry, gates, core filter."""
import io, json, os, sys, tempfile, urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.database import db as dbmod
from src.database.db import DB
from src.utils.universe import load_universe

MOCK_CHART = {'chart': {'result': [{
    'meta': {'currency': 'CHF', 'regularMarketPrice': 84.10,
             'regularMarketTime': 1784102400, 'gmtoffset': 7200,
             'exchangeTimezoneName': 'Europe/Zurich',
             'fiftyTwoWeekHigh': 89.14, 'fiftyTwoWeekLow': 47.08,
             'currentTradingPeriod': {'regular': {'start': 1, 'end': 2}}},
    'timestamp': [1783929600, 1784016000, 1784102400],
    'indicators': {'quote': [{'close': [83.0, 83.5, 84.1],
                              'open': [82.9, 83.1, 83.6],
                              'high': [83.2, 83.6, 84.2],
                              'low': [82.7, 83.0, 83.5],
                              'volume': [100, 110, 120]}],
                   'adjclose': [{'adjclose': [82.5, 83.0, 84.1]}]}}]}}


def test_mock_chart_parse_quote_and_prev_close():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'rp', os.path.join(ROOT, 'scripts', 'refresh_prices.py'))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    orig = rp._get
    rp._get = lambda url: MOCK_CHART
    try:
        meta, bars, complete = rp.fetch('ABBN.SW')
        assert meta['regularMarketPrice'] == 84.10
        assert len(bars) == 3 and bars[-1]['close'] == 84.1
        # prev close = last bar strictly before the quote date
        dt = '2026-07-15'
        older = [b for b in bars if b['date'] < dt]
        assert older[-1]['close'] == 83.5
    finally:
        rp._get = orig


def test_retry_backoff_on_429_then_success(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'rp2', os.path.join(ROOT, 'scripts', 'refresh_prices.py'))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    calls = {'n': 0}
    sleeps = []
    monkeypatch.setattr(rp.time, 'sleep', lambda s: sleeps.append(s))

    class FakeResp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls['n'] += 1
        if calls['n'] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, 'Too Many', {}, None)
        return FakeResp(json.dumps(MOCK_CHART).encode())
    monkeypatch.setattr(rp.urllib.request, 'urlopen', fake_urlopen)
    out = rp._get('http://x/chart')
    assert calls['n'] == 3
    assert rp.STATS['http_429'] >= 2
    assert out['chart']['result'][0]['meta']['currency'] == 'CHF'


def test_permanent_403_not_hammered(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'rp3', os.path.join(ROOT, 'scripts', 'refresh_prices.py'))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    calls = {'n': 0}

    def fake_urlopen(req, timeout=None):
        calls['n'] += 1
        raise urllib.error.HTTPError('u', 403, 'Forbidden', {}, None)
    monkeypatch.setattr(rp.urllib.request, 'urlopen', fake_urlopen)
    monkeypatch.setattr(rp.time, 'sleep', lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        rp._get('http://x/chart')
    assert calls['n'] == 1               # 403 breaks immediately, no blind retry


def test_core_universe_is_explicit_config():
    u = load_universe()
    core = sorted({k for _, gs in u['subgroups'] for _, cov, _ in gs for k in cov})
    assert len(core) == 30               # 30 coverage companies, one line each
    assert 'ABBN' in core and 'ETN' not in core      # Eaton is a peer
    peers = {k for _, gs in u['subgroups'] for _, _, p in gs for k in p}
    assert 'ETN' in peers


def test_prices_only_mode_rebuilds_features():
    """The v2.6 bug fix: prices_only must include the feature rebuild so it
    can never republish a stale snapshot as new."""
    import re
    src = open(os.path.join(ROOT, 'scripts', 'refresh.py')).read()
    assert re.search(r"in \('daily', 'full_refresh', 'rebuild_features',\s*"
                     r"'prices_only'\)", src)


def test_freshness_gate_blocks_on_stale_core(monkeypatch):
    tmp = tempfile.mktemp(suffix='.duckdb')
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tmp)
    d = DB(); d.init_schema()
    from datetime import datetime
    # ABBN (core) stale vs SRAIL/SCHP/SU (same-ccy groups fresher)
    rows = [('ABBN', '2026-07-10', 83.58, 89.0, 47.0, 'CHF'),
            ('SRAIL', '2026-07-13', 23.0, 30.0, 15.0, 'CHF'),
            ('SCHP', '2026-07-13', 264.0, 300.0, 200.0, 'CHF'),
            ('ALO', '2026-07-10', 15.7, 20.0, 10.0, 'EUR'),
            ('LR', '2026-07-13', 140.0, 150.0, 90.0, 'EUR'),
            ('SU', '2026-07-13', 270.0, 280.0, 190.0, 'EUR'),
            ('MRO', '2026-07-13', 4.76, 6.0, 3.9, 'GBp')]  # pounds not pence!
    d.upsert('raw_quotes', ['key', 'quote_date', 'close', 'high_52w',
                            'low_52w', 'currency'], rows, ['key'])
    from src.validation.checks import run_freshness_checks
    counts = run_freshness_checks(d, 'gate-test')
    assert counts['error'] >= 2                        # 2 stale core names
    subs = {r[0]: r[1] for r in d.fetchall(
        "SELECT subject, severity FROM validation_results "
        "WHERE check_name = 'stale_vs_market'")}
    assert subs.get('ABBN') == 'error'
    scale = d.fetchall("SELECT subject FROM validation_results "
                       "WHERE check_name = 'price_scale_implausible'")
    assert ('MRO',) in scale                           # 100x pence error caught
