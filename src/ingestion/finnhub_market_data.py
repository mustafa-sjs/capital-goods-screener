"""Finnhub market-data adapter — US intraday quotes, 1-minute candles and
company news for the "US since Europe closed" layer.

Scope is deliberately narrow: Finnhub supplements the existing Yahoo/FactIQ
infrastructure with timely US quotes and catalyst metadata. It never touches
historical daily prices, fundamentals or momentum (see provider precedence
in capital_goods_methodology.md).

Design decisions:
  * stdlib urllib, not the official finnhub-python client — three endpoints
    do not justify a new dependency tree (client pulls in requests), and the
    repo's other adapters are stdlib-only.
  * The API key is read ONLY from the FINNHUB_API_KEY environment variable
    and sent as the X-Finnhub-Token header — it never appears in URLs, so it
    cannot leak through logs or exception messages. Errors are re-raised as
    typed exceptions carrying only the endpoint path and status code.
  * A rolling-minute rate limiter throttles below the plan limit
    (default 30 req/min, configurable via config/finnhub.yaml or
    FINNHUB_MAX_RPM); HTTP 429 backs off exponentially with jitter;
    401/403 are never retried.
  * The optional WebSocket capture (benchmark Method B) needs the
    `websockets` package, installed in the GitHub Actions job only — the
    Streamlit app must never import or open sockets to Finnhub.
"""
import hashlib, json, os, random, time, urllib.error, urllib.parse, urllib.request
from collections import deque
from datetime import datetime, timezone

BASE_URL = 'https://finnhub.io/api/v1'
CONNECT_TIMEOUT = 10          # urllib exposes one timeout; applies to both
RETRY_MAX = 3
PROVIDER = 'finnhub'


class FinnhubError(Exception):
    """Base error. Message carries endpoint path + status only — no token,
    no full URL, no raw payload dumps."""


class FinnhubAuthError(FinnhubError):
    """401 — missing/invalid API key. Never retried."""


class FinnhubEntitlementError(FinnhubError):
    """403 — the account's plan does not include this resource (e.g. free
    accounts and historical 1-minute candles). Never retried; callers fall
    back to the next benchmark method."""


class FinnhubRateLimitError(FinnhubError):
    """429 persisted through every backoff attempt."""


class FinnhubDataError(FinnhubError):
    """Payload did not match the documented shape."""


def api_key():
    return os.environ.get('FINNHUB_API_KEY') or None


def enabled():
    return os.environ.get('FINNHUB_ENABLED', 'false').strip().lower() in (
        '1', 'true', 'yes', 'on')


def usage_mode():
    m = os.environ.get('FINNHUB_USAGE_MODE', 'pilot').strip().lower()
    return m if m in ('disabled', 'pilot', 'production') else 'pilot'


class RollingRateLimiter:
    """Blocks so no more than max_per_minute requests start in any rolling
    60-second window. Single-threaded by design — the adapter never issues
    uncontrolled parallel requests."""

    def __init__(self, max_per_minute):
        self.max = max(1, int(max_per_minute))
        self.stamps = deque()

    def acquire(self):
        now = time.monotonic()
        while self.stamps and now - self.stamps[0] >= 60:
            self.stamps.popleft()
        if len(self.stamps) >= self.max:
            wait = 60 - (now - self.stamps[0]) + random.uniform(0.05, 0.3)
            time.sleep(max(wait, 0))
            return self.acquire()
        self.stamps.append(time.monotonic())


class FinnhubAdapter:
    name = PROVIDER

    def __init__(self, key=None, max_rpm=None):
        self.key = key or api_key()
        if not self.key:
            raise FinnhubAuthError('FINNHUB_API_KEY is not set')
        rpm = max_rpm or os.environ.get('FINNHUB_MAX_RPM') or 30
        self.limiter = RollingRateLimiter(rpm)
        self.stats = {'requests': 0, 'ok': 0, 'failed': 0, 'http_429': 0,
                      'retried': 0, 'news_requests': 0}

    # ------------------------------------------------------------ transport
    def _http_get(self, path, params):
        """One raw request. Split out so tests monkeypatch exactly this."""
        url = f'{BASE_URL}{path}?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers={
            'X-Finnhub-Token': self.key, 'User-Agent': 'capital-goods-screener'})
        with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as r:
            return json.load(r)

    def _get(self, path, params):
        last = None
        for attempt in range(1, RETRY_MAX + 1):
            self.limiter.acquire()
            self.stats['requests'] += 1
            try:
                out = self._http_get(path, params)
                self.stats['ok'] += 1
                return out
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.stats['failed'] += 1
                    raise FinnhubAuthError(f'{path}: HTTP 401 — API key rejected') from None
                if e.code == 403:
                    self.stats['failed'] += 1
                    raise FinnhubEntitlementError(
                        f'{path}: HTTP 403 — not included in the account plan') from None
                if e.code == 429:
                    self.stats['http_429'] += 1
                    last = FinnhubRateLimitError(f'{path}: HTTP 429')
                    time.sleep(min(60, 2 ** attempt * 4 + random.uniform(0, 3)))
                else:
                    last = FinnhubError(f'{path}: HTTP {e.code}')
                    time.sleep(2 ** attempt + random.uniform(0, 1))
            except json.JSONDecodeError:
                self.stats['failed'] += 1
                raise FinnhubDataError(f'{path}: response was not valid JSON') from None
            except Exception as e:                    # timeout, DNS, conn reset
                last = FinnhubError(f'{path}: {type(e).__name__}')
                time.sleep(1.5 * attempt + random.uniform(0, 1))
            if attempt < RETRY_MAX:
                self.stats['retried'] += 1
        self.stats['failed'] += 1
        raise last

    # ------------------------------------------------------------ endpoints
    def quote(self, symbol):
        """Latest US quote -> typed dict. Raises FinnhubDataError on an
        empty/implausible payload (unknown symbols return all zeros)."""
        d = self._get('/quote', {'symbol': symbol})
        if not isinstance(d, dict) or not d.get('c') or d['c'] <= 0 or not d.get('t'):
            raise FinnhubDataError(f'/quote: empty or invalid payload for {symbol}')
        ts = datetime.fromtimestamp(d['t'], tz=timezone.utc)
        return dict(symbol=symbol,
                    price=float(d['c']),
                    prev_close=float(d['pc']) if d.get('pc') else None,
                    high=float(d['h']) if d.get('h') else None,
                    low=float(d['l']) if d.get('l') else None,
                    open=float(d['o']) if d.get('o') else None,
                    quote_ts=ts.isoformat(),
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    currency='USD',        # Finnhub US quotes are USD; the
                                           # caller cross-checks vs reference
                    provider=PROVIDER)

    def market_status(self, exchange='US'):
        """Raw market status where available; None on any failure (status is
        advisory, never load-bearing)."""
        try:
            d = self._get('/stock/market-status', {'exchange': exchange})
            return d if isinstance(d, dict) else None
        except FinnhubError:
            return None

    def candles_1m(self, symbol, start_unix, end_unix):
        """Completed one-minute bars [(utc_ts, close)]. Free accounts are not
        entitled — FinnhubEntitlementError propagates so the anchor logic
        falls back cleanly (benchmark Method A)."""
        d = self._get('/stock/candle', {'symbol': symbol, 'resolution': '1',
                                        'from': int(start_unix), 'to': int(end_unix)})
        if not isinstance(d, dict) or d.get('s') == 'no_data':
            return []
        if d.get('s') != 'ok' or 't' not in d or 'c' not in d:
            raise FinnhubDataError(f'/stock/candle: unexpected payload for {symbol}')
        return [(datetime.fromtimestamp(t, tz=timezone.utc), float(c))
                for t, c in zip(d['t'], d['c']) if c and c > 0]

    def dividends(self, symbol, date_from, date_to):
        """Declared dividends incl. ex-dates between two ISO dates. Plan
        entitlement varies — FinnhubEntitlementError propagates so callers
        degrade cleanly (same pattern as candles)."""
        raw = self._get('/stock/dividend', {'symbol': symbol,
                                            'from': date_from, 'to': date_to})
        if not isinstance(raw, list):
            raise FinnhubDataError(f'/stock/dividend: unexpected payload for {symbol}')
        out = []
        for d in raw:
            ex = d.get('date') or d.get('exDate')
            if not ex:
                continue
            out.append(dict(symbol=symbol, ex_date=ex,
                            amount=d.get('amount'),
                            currency=d.get('currency'),
                            pay_date=d.get('payDate'),
                            record_date=d.get('recordDate'),
                            provider=PROVIDER))
        return out

    def company_news(self, symbol, date_from, date_to):
        """Company news metadata (headline/summary/link only — never article
        bodies) between two ISO dates, deduplicated, newest first."""
        self.stats['news_requests'] += 1
        raw = self._get('/company-news', {'symbol': symbol, 'from': date_from,
                                          'to': date_to})
        if not isinstance(raw, list):
            raise FinnhubDataError(f'/company-news: unexpected payload for {symbol}')
        out, seen = [], set()
        now = datetime.now(timezone.utc).isoformat()
        for a in raw:
            if not isinstance(a, dict) or not a.get('headline'):
                continue
            eid = str(a.get('id') or '') or _stable_event_id(a)
            if eid in seen:
                continue
            seen.add(eid)
            pub = (datetime.fromtimestamp(a['datetime'], tz=timezone.utc)
                   if a.get('datetime') else None)
            out.append(dict(provider=PROVIDER, provider_event_id=eid,
                            symbol=symbol,
                            headline=a['headline'],
                            summary=(a.get('summary') or '')[:1000],
                            source=a.get('source'),
                            url=a.get('url'),
                            published_at=pub.isoformat() if pub else None,
                            category=a.get('category'),
                            related=a.get('related'),
                            retrieved_at=now))
        out.sort(key=lambda e: e['published_at'] or '', reverse=True)
        return out


def _stable_event_id(article):
    """Deterministic fallback id when the provider omits one: URL hash,
    else headline+timestamp hash."""
    basis = article.get('url') or f"{article.get('headline')}|{article.get('datetime')}"
    return 'h_' + hashlib.sha1(basis.encode()).hexdigest()[:20]


# ===== benchmark Method B: short-lived WebSocket trade capture ==============
# Batch-job only (GitHub Actions anchor run). Requires the optional
# `websockets` package; when it is missing the caller falls through to the
# next method. Finnhub's WS protocol authenticates via a token query
# parameter — that URL is built here and NEVER logged or echoed.

def capture_trades_around(symbols, target_utc, stop_utc, key=None,
                          max_symbols=50):
    """Subscribe to `symbols` (Finnhub symbols) until stop_utc and keep, per
    symbol, only the last trade at/before target_utc and the first after it:
    {symbol: {'before': (ts, price) | None, 'after': (ts, price) | None}}.
    Returns None when the websockets package is unavailable. No tick is
    retained beyond the two benchmark observations."""
    try:
        import asyncio
        import websockets
    except ImportError:
        return None
    key = key or api_key()
    if not key:
        raise FinnhubAuthError('FINNHUB_API_KEY is not set')
    symbols = list(symbols)[:max_symbols]
    best = {s: {'before': None, 'after': None} for s in symbols}

    async def _run():
        url = 'wss://ws.finnhub.io?token=' + urllib.parse.quote(key)
        async with websockets.connect(url, open_timeout=15, close_timeout=5) as ws:
            for s in symbols:
                await ws.send(json.dumps({'type': 'subscribe', 'symbol': s}))
            while datetime.now(timezone.utc) < stop_utc:
                budget = (stop_utc - datetime.now(timezone.utc)).total_seconds()
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(1, min(budget, 10)))
                except asyncio.TimeoutError:
                    continue
                try:
                    d = json.loads(msg)
                except ValueError:
                    continue
                if d.get('type') != 'trade':
                    continue
                for t in d.get('data', []):
                    s, p, ms = t.get('s'), t.get('p'), t.get('t')
                    if s not in best or not p or p <= 0 or not ms:
                        continue
                    ts = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                    slot = best[s]
                    if ts <= target_utc:
                        if slot['before'] is None or ts > slot['before'][0]:
                            slot['before'] = (ts, float(p))
                    elif slot['after'] is None or ts < slot['after'][0]:
                        slot['after'] = (ts, float(p))

    asyncio.run(_run())
    return best
