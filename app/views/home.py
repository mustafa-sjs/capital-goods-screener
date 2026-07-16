"""Overview — what moved, what changed, and is the data current?

Concise by design: no full screening tables here (that is the Stock
Screener's job) and no implementation details (snapshot IDs, table names
and pipeline stages live under Manage -> Data Status).
"""
import json

import pandas as pd
import streamlit as st

from components.data import (payload, last_run, latest_snapshot, q, ph,
                             data_version, status_strip, event_label,
                             core_freshness)
from components.ui import (style_table, df_show, status_badge, section,
                           page_header)

page_header('Overview',
            'What moved, what changed, and whether the data is current — '
            'across the 30 core coverage companies.')
status_strip()

D = payload(data_version())
run = last_run()
latest, n_ok, n_core, _stale = core_freshness()
c1, c2, c3, c4 = st.columns(4)
c1.metric('Latest completed market date', latest)
c2.metric('Coverage companies current', f'{n_ok} of {n_core}')
c3.metric('System last updated', str(run[2])[:16].replace('T', ' ')
          if run else 'never')
with c4:
    st.markdown('<div style="font-size:12px;color:#8a9494;margin-bottom:2px">'
                'Last update result</div>', unsafe_allow_html=True)
    kind = {'success': 'ok', 'partial': 'warn'}.get(run[3] if run else '', 'bad')
    status_badge((run[3] or 'unknown').upper() if run else 'NO RUNS', kind)
if run and run[3] == 'failed':
    st.error('The last data update failed — details under Manage → Data '
             f'Status. Notes: {run[4]}')

# ------------------------------------------------ events calendar (v2.9) ---
section('Events calendar',
        'Coverage results (bold), US peer results, Fed and macro releases. '
        'Coverage dates are confirmed from company IR calendars; “~” marks '
        'rule-based or unconfirmed dates to re-check near the day.')
from datetime import date as _date, datetime as _dt
from src.utils.universe import universe_service as _usvc
from src.features.events_calendar import upcoming_events

_wk1, _wk2 = st.columns([1, 3])
weeks_label = _wk1.selectbox('Calendar range',
                             ['This week', 'Next 2 weeks', 'Next 4 weeks',
                              'Next 8 weeks', 'Next 13 weeks'], index=1,
                             label_visibility='collapsed')
weeks = {'This week': 1, 'Next 2 weeks': 2, 'Next 4 weeks': 4,
         'Next 8 weeks': 8, 'Next 13 weeks': 13}[weeks_label]
try:
    from components.data import get_db
    _db = get_db()
except Exception:
    _db = None
events, cal_start, cal_end = upcoming_events(_db, _usvc(), weeks)
if not events:
    st.info('No calendar events in this window.')
else:
    _wk2.caption(f'{cal_start:%a %d %b} – {cal_end:%a %d %b %Y} · '
                 f'{len(events)} events · coverage results in bold · '
                 f'US peer dates via Finnhub where available')
    _today = _date.today().isoformat()
    cal_rows = []
    for e in events:
        d = _dt.strptime(e['date'], '%Y-%m-%d').date()
        mark = '▮ ' if e['category'] == 'Coverage results' else ''
        cal_rows.append({
            'Date': f"{'▶ ' if e['date'] == _today else ''}{d:%a %d %b}",
            'Event': mark + e['label']
                     + ('' if e['confirmed'] else ' (unconfirmed)'),
            'Type': e['category'],
            'When': ('' if e['confirmed'] else '~ ') + (e['detail'] or '')})
    cal_df = pd.DataFrame(cal_rows)
    st.dataframe(cal_df, hide_index=True, use_container_width=True,
                 height=min(560, 38 * (len(cal_df) + 1) + 4))
    st.caption('▮ = coverage company results · ▶ = today')
    st.download_button('Download calendar (CSV)',
                       pd.DataFrame(events).to_csv(index=False),
                       'events_calendar.csv')
    st.caption('Sources: company IR calendars (checked 16 Jul 2026), '
               'federalreserve.gov, issuer release conventions, Finnhub '
               'earnings calendar for US peers. Rule-based macro dates can '
               'shift around holidays — confirm before trading around them.')

core_rows = [r for r in D['close_rows'] if r['role'] == 'coverage']
seen_keys = set()
core_rows = [r for r in core_rows
             if not (r['key'] in seen_keys or seen_keys.add(r['key']))]

left, right = st.columns(2)
with left:
    section('Largest core-coverage moves at the last close')
    rows = sorted([r for r in core_rows if r.get('move_1d_pct') is not None],
                  key=lambda r: abs(r['move_1d_pct']), reverse=True)[:8]
    df = pd.DataFrame([{'Company': r['company'], '1D': r['move_1d_pct'],
                        '3M': r.get('move_3m_pct'), '12M': r.get('move_12m_pct')}
                       for r in rows])
    df_show(style_table(df, pct_cols=['1D', '3M', '12M']))
with right:
    section('Recent changes',
            'Deterministic day-on-day changes in valuation, fundamentals, '
            'price and trend for coverage companies. The full history is '
            'under Manage → Data Status.')
    snap = latest_snapshot()
    ev = q(f'SELECT key, event_type, detail FROM daily_change_events '
           f'WHERE snapshot_date = {ph()} ORDER BY event_type', [snap]) if snap else []
    core_set = {r['key'] for r in core_rows}
    recs = []
    for k, etype, detail in ev:
        if k not in core_set:
            continue
        try:
            d = json.loads(detail)
            note = d.get('note') or ''
        except Exception:
            note = str(detail)
        recs.append({'Company': D['names'].get(k, k),
                     'What changed': event_label(etype), 'Detail': note})
    if recs:
        df_show(pd.DataFrame(recs).head(12))
    else:
        st.info('No material changes since the previous market update.')

section('New trend signals',
        'Confirmed crossovers of the default price-trend setting within '
        'the last 15 sessions.')
sigs = [r for r in D['screener']
        if (r.get('recent_signal') or 'No recent crossover')
        != 'No recent crossover']
if sigs:
    df = pd.DataFrame([{'Company': r['company'], 'Signal': r['recent_signal'],
                        'Trend': r.get('trend'),
                        'Momentum change': r.get('momentum_change'),
                        '3M vs peers': r.get('rel_3m_pct')} for r in sigs])
    df_show(style_table(df, pct_cols=['3M vs peers'],
                        class_cols=['Signal', 'Trend', 'Momentum change']))
else:
    st.caption('No new trend crossovers in the recent window.')

left2, right2 = st.columns(2)
sc = sorted([r for r in D['screener'] if r.get('prem_disc_vs_peers_pct') is not None],
            key=lambda r: r['prem_disc_vs_peers_pct'])
with left2:
    section('Largest discounts to direct peers',
            'EV/EBITDA versus the median of each company\'s direct peers. '
            'A discount is a fact about price, not a recommendation.')
    df = pd.DataFrame([{'Company': r['company'], 'EV/EBITDA': r['ev_ebitda_ltm'],
                        'vs direct peers': r['prem_disc_vs_peers_pct'],
                        'Trend': r.get('trend')} for r in sc[:6]])
    df_show(style_table(df, mult_cols=['EV/EBITDA'], class_cols=['Trend'],
                        val_scale_col='vs direct peers',
                        pct_cols=['vs direct peers']))
with right2:
    section('Largest premiums to direct peers')
    prem_only = [r for r in sc if r['prem_disc_vs_peers_pct'] > 0][-6:][::-1]
    df = pd.DataFrame([{'Company': r['company'], 'EV/EBITDA': r['ev_ebitda_ltm'],
                        'vs direct peers': r['prem_disc_vs_peers_pct'],
                        'Trend': r.get('trend')} for r in prem_only])
    df_show(style_table(df, mult_cols=['EV/EBITDA'], class_cols=['Trend'],
                        val_scale_col='vs direct peers',
                        pct_cols=['vs direct peers']))

warn = q("""SELECT count(DISTINCT subject) FROM validation_results
            WHERE severity IN ('warning','error','critical')""")
n_warn = warn[0][0] if warn else 0
if n_warn:
    st.caption(f'⚠ {n_warn} data-quality findings on record — explained in '
               'plain English under Manage → Data Status.')
