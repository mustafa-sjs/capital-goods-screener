"""Manual CSV fallback adapter.

If every automated source is down, prices can be imported by hand:

    python scripts/import_prices.py --file prices.csv

CSV columns (header required, extra columns ignored):
    key,price_date,close[,open,high,low,volume,currency]

Rows upsert on (key, price_date, source='manual_csv') — idempotent.
"""
import csv

from .base import PriceDataSource


class ManualCSVAdapter(PriceDataSource):
    name = 'manual_csv'

    def __init__(self, path):
        self.path = path

    def rows(self):
        with open(self.path, newline='') as fh:
            for r in csv.DictReader(fh):
                yield dict(key=r['key'].strip(), date=r['price_date'].strip(),
                           open=_f(r.get('open')), high=_f(r.get('high')),
                           low=_f(r.get('low')), close=_f(r.get('close')),
                           volume=_f(r.get('volume')),
                           currency=(r.get('currency') or '').strip() or None,
                           source=self.name)


class MockPriceAdapter(PriceDataSource):
    """Deterministic fixture adapter for tests."""
    name = 'mock'

    def __init__(self, quote=None, bars=None):
        self._quote = quote or {}
        self._bars = bars or []

    def get_quote_and_bars(self, symbol, rng='1mo'):
        q = dict(self._quote); q['symbol'] = symbol; q['source'] = self.name
        return q, list(self._bars)


def _f(x):
    try:
        return float(x) if x not in (None, '') else None
    except ValueError:
        return None
