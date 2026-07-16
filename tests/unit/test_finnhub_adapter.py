"""Finnhub adapter tests — every case is mocked; the live API is NEVER
called (spec §22). Transport behaviour is exercised by monkeypatching
FinnhubAdapter._http_get, the single raw-request seam."""
import io, json, os, sys, urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.ingestion import finnhub_market_data as fmd
from src.ingestion.finnhub_market_data import (FinnhubAdapter, FinnhubAuthError,
                                               FinnhubDataError,
                                               FinnhubEntitlementError,
                                               FinnhubRateLimitError,
                                               RollingRateLimiter,
                                               _stable_event_id)

QUOTE = {'c': 342.5, 'pc': 337.1, 'h': 343.0, 'l': 336.0, 'o': 337.5,
         't': 1752682200, 'd': 5.4, 'dp': 1.6}


def adapter(monkeypatch, responses):
    """Adapter whose _http_get pops canned responses (dict payloads or
    exceptions) and never sleeps."""
    monkeypatch.setenv('FINNHUB_API_KEY', 'test-key-not-real')
    monkeypatch.setattr(fmd.time, 'sleep', lambda s: None)
    ad = FinnhubAdapter()
    calls = {'n': 0, 'paths': []}

    def fake(path, params):
        calls['n'] += 1
        calls['paths'].append(path)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(ad, '_http_get', fake)
    ad._calls = calls
    return ad


def http_error(code):
    return urllib.error.HTTPError('url', code, 'msg', {}, io.BytesIO(b''))


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv('FINNHUB_API_KEY', raising=False)
    assert fmd.api_key() is None
    with pytest.raises(FinnhubAuthError):
        FinnhubAdapter()


def test_quote_parsing(monkeypatch):
    ad = adapter(monkeypatch, [dict(QUOTE)])
    q = ad.quote('ETN')
    assert q['symbol'] == 'ETN' and q['price'] == 342.5
    assert q['prev_close'] == 337.1 and q['currency'] == 'USD'
    assert q['provider'] == 'finnhub'
    assert q['quote_ts'].startswith('2025') or q['quote_ts'].startswith('2026')
    assert '+00:00' in q['quote_ts']            # timezone-aware UTC


def test_quote_invalid_payload(monkeypatch):
    ad = adapter(monkeypatch, [{'c': 0, 'pc': 0, 't': 0}])
    with pytest.raises(FinnhubDataError):
        ad.quote('ZZZQ')                        # unknown symbols return zeros


def test_invalid_key_401_never_retried(monkeypatch):
    ad = adapter(monkeypatch, [http_error(401)])
    with pytest.raises(FinnhubAuthError) as e:
        ad.quote('ETN')
    assert ad._calls['n'] == 1                  # no retry on auth failure
    assert 'test-key-not-real' not in str(e.value)


def test_entitlement_403_never_retried(monkeypatch):
    ad = adapter(monkeypatch, [http_error(403)])
    with pytest.raises(FinnhubEntitlementError):
        ad.candles_1m('ETN', 0, 60)
    assert ad._calls['n'] == 1


def test_429_backs_off_then_raises(monkeypatch):
    ad = adapter(monkeypatch, [http_error(429)] * 3)
    with pytest.raises(FinnhubRateLimitError):
        ad.quote('ETN')
    assert ad._calls['n'] == 3                  # RETRY_MAX attempts
    assert ad.stats['http_429'] == 3


def test_timeout_retries_then_raises(monkeypatch):
    ad = adapter(monkeypatch, [TimeoutError('t')] * 3)
    with pytest.raises(fmd.FinnhubError):
        ad.quote('ETN')
    assert ad._calls['n'] == 3


def test_transient_error_then_success(monkeypatch):
    ad = adapter(monkeypatch, [http_error(500), dict(QUOTE)])
    assert ad.quote('ETN')['price'] == 342.5
    assert ad.stats['retried'] == 1


def test_candles_parsing_and_no_data(monkeypatch):
    ad = adapter(monkeypatch, [
        {'s': 'ok', 't': [1752682140, 1752682200], 'c': [342.0, 342.5]},
        {'s': 'no_data'}])
    bars = ad.candles_1m('ETN', 0, 1752682260)
    assert len(bars) == 2 and bars[1][1] == 342.5
    assert ad.candles_1m('ETN', 0, 60) == []


def test_news_parsing_dedupe_and_id_fallback(monkeypatch):
    arts = [
        {'id': 101, 'headline': 'Eaton raises guidance', 'summary': 's1',
         'source': 'Reuters', 'url': 'https://x/1', 'datetime': 1752684000,
         'category': 'company', 'related': 'ETN'},
        {'id': 101, 'headline': 'Eaton raises guidance', 'summary': 'dupe',
         'source': 'Reuters', 'url': 'https://x/1', 'datetime': 1752684000,
         'category': 'company', 'related': 'ETN'},
        {'id': None, 'headline': 'Sector note', 'summary': '', 'source': 'Wire',
         'url': 'https://x/2', 'datetime': 1752680000, 'category': 'company',
         'related': 'ETN'},
        {'headline': None},                      # malformed -> dropped
    ]
    ad = adapter(monkeypatch, [arts])
    out = ad.company_news('ETN', '2026-07-16', '2026-07-16')
    assert len(out) == 2                         # dupe + malformed removed
    assert out[0]['headline'] == 'Eaton raises guidance'   # newest first
    assert out[1]['provider_event_id'].startswith('h_')    # deterministic fallback
    assert ad.stats['news_requests'] == 1


def test_stable_event_id_deterministic():
    a = {'url': 'https://example.com/story'}
    assert _stable_event_id(a) == _stable_event_id(dict(a))
    b = {'headline': 'X', 'datetime': 1}
    assert _stable_event_id(b) != _stable_event_id(a)


def test_rate_limiter_blocks_over_limit(monkeypatch):
    rl = RollingRateLimiter(2)
    waited = []
    monkeypatch.setattr(fmd.time, 'sleep', lambda s: waited.append(s) or
                        rl.stamps.popleft())    # simulate window expiry
    rl.acquire(); rl.acquire(); rl.acquire()
    assert waited, 'third call within the window must wait'


def test_enabled_and_usage_mode_flags(monkeypatch):
    monkeypatch.setenv('FINNHUB_ENABLED', 'TRUE')
    assert fmd.enabled()
    monkeypatch.setenv('FINNHUB_ENABLED', 'no')
    assert not fmd.enabled()
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'production')
    assert fmd.usage_mode() == 'production'
    monkeypatch.setenv('FINNHUB_USAGE_MODE', 'bogus')
    assert fmd.usage_mode() == 'pilot'           # safe default
