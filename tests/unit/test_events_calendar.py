"""Events calendar engine: rule arithmetic, curated/FOMC windows, provider
merge. No network — the Finnhub earnings fetch is exercised with a mock."""
import json, os, sys, tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.database import db as dbmod
from src.database.db import DB
from src.features import events_calendar as ec


def tmp_db(monkeypatch):
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tempfile.mktemp(suffix='.duckdb'))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    d = DB()
    d.init_schema()
    return d


def test_rule_arithmetic():
    assert ec._business_day(2026, 8, 1) == date(2026, 8, 3)    # Sat 1st -> Mon
    assert ec._business_day(2026, 8, 3) == date(2026, 8, 5)    # 3rd b-day
    assert ec._first_friday(2026, 8) == date(2026, 8, 7)
    assert ec._third_wednesday(2026, 7) == date(2026, 7, 15)
    assert ec._day_24_weekday(2026, 10) == date(2026, 10, 23)  # 24th=Sat -> Fri
    assert ec._last_day(2026, 12) == date(2026, 12, 31)


def test_macro_and_fomc_windows():
    evs = ec.macro_events(date(2026, 8, 1), date(2026, 8, 31))
    labels = {e['label'] for e in evs}
    assert any('ISM Manufacturing' in x for x in labels)
    assert any('Payrolls' in x for x in labels)
    ism = next(e for e in evs if 'ISM Manufacturing' in e['label'])
    assert ism['date'] == '2026-08-03' and ism['confirmed']
    pmis = next(e for e in evs if 'Flash PMIs' in e['label'])
    assert not pmis['confirmed']                       # approximate rule
    fed = ec.fomc_events(date(2026, 7, 20), date(2026, 8, 2))
    assert len(fed) == 1 and fed[0]['date'] == '2026-07-29'
    assert ec.fomc_events(date(2026, 8, 1), date(2026, 9, 1)) == []


def test_curated_results_window_and_flags():
    svc = dict(names={'SIE': 'Siemens AG', 'WEIR': 'Weir Group plc'})
    evs = ec.curated_events(date(2026, 7, 27), date(2026, 8, 9), svc)
    by_key = {e['key']: e for e in evs}
    assert by_key['SIE']['date'] == '2026-08-06'
    assert by_key['SIE']['confirmed'] and 'Siemens' in by_key['SIE']['label']
    assert not by_key['WEIR']['confirmed']             # estimated date flagged
    assert 'SRAIL' not in by_key                       # outside the window


def test_finnhub_earnings_fetch_and_merge(monkeypatch):
    db = tmp_db(monkeypatch)
    svc = dict(finnhub={'ETN': 'ETN', 'SIE': 'SIEGY'},
               names={'ETN': 'Eaton', 'SIE': 'Siemens AG'})

    class MockAdapter:
        def _get(self, path, params):
            assert path == '/calendar/earnings'
            return {'earningsCalendar': [
                {'date': '2026-08-05', 'symbol': params['symbol'],
                 'quarter': 2, 'year': 2026, 'hour': 'bmo',
                 'epsEstimate': 2.95}]}

    m = ec.fetch_finnhub_earnings(db, 'r1', svc, MockAdapter())
    assert m['requested'] == 1 and m['events'] == 1    # SIE curated -> skipped
    # idempotent
    ec.fetch_finnhub_earnings(db, 'r1', svc, MockAdapter())
    assert db.fetchall('SELECT count(*) FROM calendar_events')[0][0] == 1
    events, start, end = ec.upcoming_events(db, svc, weeks=13,
                                            start=date(2026, 7, 16))
    peer = [e for e in events if e['category'] == 'Peer results']
    assert peer and peer[0]['label'].startswith('Eaton')
    assert peer[0]['detail'] == 'before open'
    # sorted by date, coverage results precede macro on the same date
    dates = [e['date'] for e in events]
    assert dates == sorted(dates)


def test_upcoming_events_rolls_off_past_days():
    svc = dict(names={})
    events, start, end = ec.upcoming_events(None, svc, weeks=2,
                                            start=date(2026, 7, 18))
    assert start == date(2026, 7, 18)                  # from today, not Monday
    assert end == date(2026, 7, 31)
    assert all(start.isoformat() <= e['date'] <= end.isoformat()
               for e in events)
    # the 16-17 Jul reporting cluster has rolled off; late-July wave remains
    assert not any(e['date'] < '2026-07-18' for e in events)
    cats = {e['category'] for e in events}
    assert 'Coverage results' in cats


def test_dividends_fetch_entitlement_and_merge(monkeypatch):
    from src.ingestion.finnhub_market_data import FinnhubEntitlementError
    db = tmp_db(monkeypatch)
    svc = dict(finnhub={'ETN': 'ETN', 'CAT': 'CAT'},
               names={'ETN': 'Eaton', 'CAT': 'Caterpillar'})

    class Divs:
        def dividends(self, sym, a, b):
            return [dict(symbol=sym, ex_date='2026-08-14', amount=1.04,
                         currency='USD', pay_date='2026-08-28',
                         record_date=None, provider='finnhub')] \
                if sym == 'ETN' else []

    m = ec.fetch_finnhub_dividends(db, 'r1', svc, Divs())
    assert m['entitled'] and m['events'] == 1
    events, *_ = ec.upcoming_events(db, svc, weeks=8, start=date(2026, 7, 18))
    exd = [e for e in events if e['category'] == 'Ex-dividend']
    assert len(exd) == 1 and exd[0]['label'] == 'Eaton — Ex-dividend 1.04 USD'

    class NotEntitled:
        def dividends(self, sym, a, b):
            raise FinnhubEntitlementError('/stock/dividend: HTTP 403')

    m2 = ec.fetch_finnhub_dividends(db, 'r2', svc, NotEntitled())
    assert not m2['entitled'] and m2['requested'] == 1   # stopped at first 403


def test_times_converted_to_uk():
    assert ec.to_uk_time('07:20 CEST', date(2026, 7, 17)) == '06:20 UK'
    assert ec.to_uk_time('08:30 ET', date(2026, 7, 22)) == '13:30 UK'
    assert ec.to_uk_time('14:00 ET statement', date(2026, 7, 29)) == '19:00 UK statement'
    assert ec.to_uk_time('08:30 EEST', date(2026, 7, 22)) == '06:30 UK'
    assert ec.to_uk_time('~11:30 CEST', date(2026, 7, 17)) == '~10:30 UK'
    assert ec.to_uk_time('10:00 ET', date(2026, 1, 4)) == '15:00 UK'   # winter
    assert ec.to_uk_time('before open', date(2026, 7, 17)) == 'before open'
    assert ec.to_uk_time(None, date(2026, 7, 17)) is None
    svc = dict(names={'VOLVB': 'Volvo AB (B)'})
    evs = ec.curated_events(date(2026, 7, 17), date(2026, 7, 17), svc)
    volvo = next(e for e in evs if e['key'] == 'VOLVB')
    assert volvo['detail'] == '06:20 UK'
