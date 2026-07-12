"""Replaceable market-data adapter interface.

Every adapter returns the same standardised shapes so nothing downstream
knows which provider supplied a price:

  quote: dict(symbol, price, prev_close, quote_date, currency,
              high_52w, low_52w, source)
  bar:   dict(date, open, high, low, close, volume, currency, source)

Adapters:
  YahooFinanceAdapter  - src/ingestion/yahoo_prices.py (default, keyless)
  ManualCSVAdapter     - src/ingestion/manual_csv.py   (fallback import)
  MockPriceAdapter     - src/ingestion/mock_prices.py  (tests)

If the default source dies: the platform keeps serving the latest stored
observations (marked stale by validation), and a new adapter only has to
implement this interface. Never auto-subscribe to a paid source.
"""


class PriceDataSource:
    name = 'abstract'

    def get_quote_and_bars(self, symbol, rng='1mo'):
        """Return (quote_dict, [completed_bar_dicts]) for one symbol."""
        raise NotImplementedError
