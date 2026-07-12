import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.database import db as dbmod
from src.database.db import DB
from src.utils.universe import load_universe
from src.ingestion.manual_csv import MockPriceAdapter


def _tmp_db(monkeypatch):
    tmp = tempfile.mktemp(suffix='.duckdb')
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tmp)
    d = DB()
    d.init_schema()
    return d


def test_upsert_idempotent(monkeypatch):
    d = _tmp_db(monkeypatch)
    rows = [('ABBN', '2026-07-10', None, None, None, 83.58, 100, 'CHF',
             'yahoo', None, 'ok')]
    cols = ['key', 'price_date', 'open', 'high', 'low', 'close', 'volume',
            'currency', 'source', 'ingested_at', 'quality']
    keys = ['key', 'price_date', 'source']
    d.upsert('raw_daily_prices', cols, rows, keys)
    d.upsert('raw_daily_prices', cols, rows, keys)          # run twice
    assert d.fetchall('SELECT count(*) FROM raw_daily_prices')[0][0] == 1
    # update path: same key, new close
    rows[0] = rows[0][:5] + (84.00,) + rows[0][6:]
    d.upsert('raw_daily_prices', cols, rows, keys)
    got = d.fetchall('SELECT close, count(*) OVER () FROM raw_daily_prices')[0]
    assert got == (84.00, 1)


def test_universe_config_integrity():
    u = load_universe()
    assert u and len(u['sec']) == 79
    covered = set()
    for sg, groups in u['subgroups']:
        for disp, cov, peers in groups:
            covered.update(cov + peers)
            assert cov, f'{disp}: empty coverage'
            assert peers, f'{disp}: empty peer basket'
    assert covered == set(u['sec']), 'orphan securities or missing definitions'
    assert set(u['yahoo']) == set(u['sec']), 'every security needs a yahoo symbol'


def test_config_matches_engine_literals():
    """The YAML config and the engine's no-dependency fallback literals must
    stay equivalent — this is the guard against dual-maintenance drift."""
    src = open(os.path.join(ROOT, 'scripts', 'compute_metrics.py')).read()
    ns = {'__file__': os.path.join(ROOT, 'scripts', 'compute_metrics.py')}
    exec(compile(src[:src.find('# config override')], 'lit', 'exec'), ns)
    u = load_universe()
    assert u['sec'] == ns['SEC']
    assert [(a, [tuple(x) for x in b]) for a, b in u['subgroups']] == \
           [(a, [tuple(x) for x in b]) for a, b in ns['SUBGROUPS']]


def test_mock_adapter_shape():
    ad = MockPriceAdapter(quote={'price': 10.0, 'prev_close': 9.5},
                          bars=[{'date': '2026-07-10', 'close': 10.0}])
    q, bars = ad.get_quote_and_bars('TEST')
    assert q['symbol'] == 'TEST' and q['source'] == 'mock'
    assert bars[0]['close'] == 10.0
