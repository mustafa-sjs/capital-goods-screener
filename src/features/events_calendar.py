"""Events calendar engine (v2.9).

Three event sources, merged into one dated list for the Overview calendar:
  1. Curated coverage-company results + one-off events and the FOMC
     schedule — config/events_calendar.yaml (confirmed IR dates; anything
     estimated carries confirmed: false and renders with a caveat).
  2. Rule-generated recurring macro releases (ISM, payrolls, flash PMIs,
     ABI, China PMI) — deterministic date arithmetic, no provider, no
     network; approximate rules are labelled as such.
  3. Finnhub earnings calendar for the mapped US peers — fetched by the
     refresh job (never on page load) into calendar_events.

Every event dict: date (iso), label, category ('Coverage results' |
'Peer results' | 'Fed' | 'Macro' | 'Company event'), key (or None),
confirmed (bool), detail (time hint / provider extras).
"""
import json, os
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG_PATH = os.path.join(ROOT, 'config', 'events_calendar.yaml')

_CFG = {}


def calendar_config(path=CFG_PATH):
    if not _CFG:
        import yaml
        _CFG.update(yaml.safe_load(open(path)) or {})
    return _CFG


# ============================= rule arithmetic ==============================

def _business_day(year, month, n):
    """The n-th business day of a month (weekend-aware; public holidays are
    why rule events stay 'approximate' unless the issuer fixes the day)."""
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _first_friday(year, month):
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _third_wednesday(year, month):
    d = date(year, month, 1)
    first_wed = d + timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + timedelta(days=14)


def _day_24_weekday(year, month):
    """~24th, rolled back to Friday when it lands on a weekend."""
    d = date(year, month, 24)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _last_day(year, month):
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


_RULES = {
    'first_business_day': lambda y, m: _business_day(y, m, 1),
    'third_business_day': lambda y, m: _business_day(y, m, 3),
    'first_friday': _first_friday,
    'third_wednesday': _third_wednesday,
    'day_24_weekday': _day_24_weekday,
    'last_day': _last_day,
}


def _months_between(start, end):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        yield y, m
        y, m = y + (m == 12), m % 12 + 1


def macro_events(start, end, cfg=None):
    cfg = cfg or calendar_config()
    out = []
    for slug, spec in (cfg.get('macro_rules') or {}).items():
        fn = _RULES.get(spec.get('rule'))
        if not fn:
            continue
        for y, m in _months_between(start, end):
            d = fn(y, m)
            if start <= d <= end:
                out.append(dict(date=d.isoformat(), label=spec['label'],
                                category='Macro', key=slug,
                                confirmed=not spec.get('approximate', False),
                                detail=spec.get('time')))
    return out


def fomc_events(start, end, cfg=None):
    cfg = cfg or calendar_config()
    out = []
    for pair in cfg.get('fomc') or []:
        d1, d2 = [x if isinstance(x, date) else
                  datetime.strptime(str(x), '%Y-%m-%d').date() for x in pair]
        if start <= d2 <= end or start <= d1 <= end:
            out.append(dict(date=d2.isoformat(),
                            label='FOMC decision + press conference '
                                  f'(meeting {d1:%d}–{d2:%d %b})',
                            category='Fed', key='fomc', confirmed=True,
                            detail='14:00 ET statement'))
    return out


def curated_events(start, end, svc=None, cfg=None):
    cfg = cfg or calendar_config()
    names = (svc or {}).get('names', {})
    out = []
    for k, spec in (cfg.get('results') or {}).items():
        d = spec['date'] if isinstance(spec['date'], date) else \
            datetime.strptime(str(spec['date']), '%Y-%m-%d').date()
        if start <= d <= end:
            out.append(dict(date=d.isoformat(),
                            label=f"{names.get(k, k)} — {spec['label']}",
                            category='Coverage results', key=k,
                            confirmed=bool(spec.get('confirmed', True)),
                            detail=spec.get('time')))
    for e in cfg.get('extra_events') or []:
        d = e['date'] if isinstance(e['date'], date) else \
            datetime.strptime(str(e['date']), '%Y-%m-%d').date()
        if start <= d <= end:
            out.append(dict(date=d.isoformat(), label=e['label'],
                            category='Company event', key=e.get('key'),
                            confirmed=bool(e.get('confirmed', True)),
                            detail=None))
    return out


# ============================= Finnhub earnings =============================

def fetch_finnhub_earnings(db, run_id, svc, adapter, weeks_ahead=9):
    """US peers' next results dates from Finnhub's earnings calendar into
    calendar_events. One request per mapped symbol, throttled by the
    adapter's limiter; run at most daily (see refresh.py guard)."""
    from src.ingestion import finnhub_market_data as fmd
    start = date.today()
    end = start + timedelta(weeks=weeks_ahead)
    m = {'requested': 0, 'events': 0, 'failed': 0}
    rows = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    covered = set((calendar_config().get('results') or {}))
    for k, sym in sorted(svc['finnhub'].items()):
        if k in covered:
            continue                      # curated coverage dates win
        m['requested'] += 1
        try:
            d = adapter._get('/calendar/earnings',
                             {'from': start.isoformat(), 'to': end.isoformat(),
                              'symbol': sym})
        except fmd.FinnhubAuthError:
            raise
        except fmd.FinnhubError:
            m['failed'] += 1
            continue
        for e in (d or {}).get('earningsCalendar') or []:
            if not e.get('date'):
                continue
            hour = {'bmo': 'before open', 'amc': 'after close',
                    'dmh': 'during market'}.get(e.get('hour'), e.get('hour'))
            detail = dict(hour=hour, eps_estimate=e.get('epsEstimate'),
                          quarter=e.get('quarter'), year=e.get('year'))
            rows.append((e['date'], 'results', k,
                         f"Q{e.get('quarter', '?')} {e.get('year', '')} earnings",
                         'finnhub', True, json.dumps(detail), now))
    m['events'] = db.upsert('calendar_events',
                            ['event_date', 'event_type', 'subject', 'title',
                             'source', 'confirmed', 'details', 'updated_at'],
                            rows, ['event_date', 'event_type', 'subject'])
    return m


def provider_events(db, start, end, svc):
    """Stored provider rows (Finnhub US peer earnings) as event dicts."""
    names = svc.get('names', {})
    try:
        rows = db.fetchall(
            f'SELECT event_date, subject, title, confirmed, details '
            f'FROM calendar_events WHERE event_type = {db.ph} '
            f'AND event_date >= {db.ph} AND event_date <= {db.ph}',
            ['results', start.isoformat(), end.isoformat()])
    except Exception:
        return []
    out = []
    for d, k, title, conf, details in rows:
        hint = None
        try:
            hint = (json.loads(details) or {}).get('hour')
        except Exception:
            pass
        out.append(dict(date=str(d)[:10],
                        label=f'{names.get(k, k)} — {title}',
                        category='Peer results', key=k,
                        confirmed=bool(conf), detail=hint))
    return out


# ============================= merged view ==================================

def upcoming_events(db, svc, weeks=1, start=None):
    """Every event from the Monday of the current week to N weeks out,
    merged and sorted. Pure config/rule events need no database or network;
    provider rows are added when present."""
    today = start or date.today()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(weeks=weeks, days=-1)
    cfg = calendar_config()
    events = (curated_events(monday, end, svc, cfg)
              + fomc_events(monday, end, cfg)
              + macro_events(monday, end, cfg))
    if db is not None:
        prov = provider_events(db, monday, end, svc)
        have = {(e['date'], e['key']) for e in events}
        events += [e for e in prov if (e['date'], e['key']) not in have]
    order = {'Coverage results': 0, 'Peer results': 1, 'Fed': 2,
             'Company event': 3, 'Macro': 4}
    events.sort(key=lambda e: (e['date'], order.get(e['category'], 9)))
    return events, monday, end
