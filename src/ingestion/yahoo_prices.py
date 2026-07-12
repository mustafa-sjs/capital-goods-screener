"""Yahoo Finance adapter — stdlib only, no API key, no yfinance dependency.

Wraps the proven fetch logic from scripts/refresh_prices.py behind the
PriceDataSource interface. Previous close is derived from the last completed
bar strictly before the quote date (Yahoo's chartPreviousClose refers to the
range start and is wrong for this). Bars from a session still in progress
are returned in the quote but excluded from completed bars.
"""
import json, urllib.request
from datetime import datetime, timezone

from .base import PriceDataSource

UA = {'User-Agent': 'Mozilla/5.0'}


def _chart(symbol, rng='1mo', interval='1d'):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
           f'?range={rng}&interval={interval}')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)['chart']['result'][0]


class YahooFinanceAdapter(PriceDataSource):
    name = 'yahoo'

    def get_quote_and_bars(self, symbol, rng='1mo'):
        res = _chart(symbol, rng)
        meta = res['meta']
        gmtoff = meta.get('gmtoffset', 0)
        q = res['indicators']['quote'][0]
        bars, seen = [], {}
        for i, t in enumerate(res.get('timestamp') or []):
            c = q['close'][i]
            if c is None:
                continue
            d = datetime.fromtimestamp(t + gmtoff, tz=timezone.utc).strftime('%Y-%m-%d')
            seen[d] = dict(date=d, open=q['open'][i], high=q['high'][i],
                           low=q['low'][i], close=c, volume=q['volume'][i],
                           currency=meta.get('currency'), source=self.name)
        bars = sorted(seen.values(), key=lambda b: b['date'])
        reg = (meta.get('currentTradingPeriod') or {}).get('regular') or {}
        session_open = (meta.get('regularMarketTime') and reg.get('end')
                        and meta['regularMarketTime'] < reg['end'])
        completed = bars[:-1] if (session_open and bars) else bars
        dt = datetime.fromtimestamp(meta['regularMarketTime'] + gmtoff,
                                    tz=timezone.utc).strftime('%Y-%m-%d')
        older = [b for b in bars if b['date'] < dt]
        quote = dict(symbol=symbol, price=meta.get('regularMarketPrice'),
                     prev_close=older[-1]['close'] if older else None,
                     quote_date=dt, currency=meta.get('currency'),
                     high_52w=meta.get('fiftyTwoWeekHigh'),
                     low_52w=meta.get('fiftyTwoWeekLow'), source=self.name)
        return quote, completed

    def intraday_price_at(self, symbol, target_hhmm, tz_name='Europe/London'):
        """Last 5-minute bar at/before target local time today. Returns
        (price, iso_timestamp, currency) or (None, None, None)."""
        from zoneinfo import ZoneInfo
        res = _chart(symbol, rng='1d', interval='5m')
        meta = res['meta']
        q = res['indicators']['quote'][0]
        tz = ZoneInfo(tz_name)
        target_h, target_m = map(int, target_hhmm.split(':'))
        best = (None, None)
        for i, t in enumerate(res.get('timestamp') or []):
            c = q['close'][i]
            if c is None:
                continue
            local = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(tz)
            if (local.hour, local.minute) <= (target_h, target_m):
                best = (c, local.isoformat())
        return best[0], best[1], meta.get('currency')
