"""Compare Companies — how do selected companies differ across valuation,
fundamentals and share-price performance?

Reuses the engine's screener payload and the canonical price history; no
separate calculation engine.
"""
import os, sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from components.data import payload, data_version, status_strip, price_history
from components.ui import df_show, page_header, section, SERIES
from src.utils.universe import universe_service
from src.utils import metrics as M

page_header('Compare Companies',
            'Put two to five coverage companies side by side across '
            'valuation, fundamentals and share-price performance.')
status_strip()

D = payload(data_version())
svc = universe_service()
scr = {r['key']: r for r in D['screener']}
options = [k for k in svc['core'] if k in scr]
sel = st.multiselect('Companies (2–5)', options, default=options[:3],
                     max_selections=5,
                     format_func=lambda k: f"{svc['names'][k]} "
                                           f"({svc['tickers'][k]})")
if len(sel) < 2:
    st.info('Choose at least two coverage companies to compare.')
    st.stop()

# ------------------------------------------------- side-by-side metrics ----
ROWS = [
    ('subgroup', None), ('price', None), ('mcap_usd_bn', None),
    ('ev_ebitda_ltm', 'Valuation'), ('prem_disc_vs_peers_pct', None),
    ('prem_disc_vs_sector_pct', None), ('hist_percentile', None),
    ('pe_ltm', None), ('fcf_yield_pct', None),
    ('rev_growth_pct', 'Fundamentals'), ('ebitda_margin_pct', None),
    ('margin_chg_pp', None), ('fcf_conversion', None), ('nd_ebitda', None),
    ('fundamental_state', None),
    ('rel_3m_pct', 'Share-price performance'), ('rel_12m_pct', None),
    ('drawdown_52w_pct', None),
    ('trend', 'Price trend'), ('momentum_change', None),
    ('recent_signal', None),
]

FMT = {'pct_signed': lambda v: f'{v:+.1f}%', 'pp': lambda v: f'{v:+.1f}pp',
       'pct': lambda v: f'{v:.1f}%', 'mult': lambda v: f'{v:.1f}×',
       'num': lambda v: f'{v:,.2f}', 'usd_bn': lambda v: f'{v:,.1f}',
       'percentile': lambda v: f'{v:.0f}th', 'price': lambda v: f'{v:,.2f}',
       'int': lambda v: f'{v:,.0f}'}


def fmt(mid, v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return M.METRIC_DEFINITIONS.get(mid, {}).get('missing', 'Not available')
    d = M.METRIC_DEFINITIONS.get(mid)
    if not d:
        return str(v)
    fn = FMT.get(d['format'])
    try:
        return fn(float(v)) if fn else str(v)
    except (TypeError, ValueError):
        return str(v)


table = []
for mid, sect in ROWS:
    row = {'Metric': M.label(mid)}
    for k in sel:
        row[svc['names'][k]] = fmt(mid, scr[k].get(mid))
    if sect:
        table.append({'Metric': f'— {sect} —',
                      **{svc['names'][k]: '' for k in sel}})
    table.append(row)
section('Side by side')
df_show(pd.DataFrame(table),
        height=int(35.5 * (len(table) + 1)) + 4,
        pinned=('Metric',),
        help_map={'Metric': 'Definitions are in Manage → Methodology.'})
st.download_button('Download comparison (CSV)',
                   pd.DataFrame(table).to_csv(index=False),
                   'compare_companies.csv')

# ------------------------------------------------- relative performance ----
section('Share-price performance, indexed',
        'Total-return price (dividends reinvested), each company indexed to '
        '100 at the start of the window.')
window = st.radio('Window', ['6M', '1Y', '3Y', '5Y', 'Max'], index=1,
                  horizontal=True)
DAYS = {'6M': 126, '1Y': 252, '3Y': 756, '5Y': 1260, 'Max': None}
lines = []
for k in sel:
    hp, _src = price_history(k, data_version())
    ser = hp[['session_date', 'close_tr']].dropna()
    n = DAYS[window]
    if n:
        ser = ser.tail(n)
    if ser.empty or not ser['close_tr'].iloc[0]:
        continue
    base = ser['close_tr'].iloc[0]
    lines.append(pd.DataFrame({
        'Date': pd.to_datetime(ser['session_date']),
        'Indexed total return': ser['close_tr'] / base * 100,
        'Company': svc['names'][k]}))
if lines:
    ldf = pd.concat(lines)
    chart = alt.Chart(ldf).mark_line().encode(
        x=alt.X('Date:T', title=None),
        y=alt.Y('Indexed total return:Q', title='Indexed total return (start = 100)',
                scale=alt.Scale(zero=False)),
        color=alt.Color('Company:N', scale=alt.Scale(range=SERIES),
                        legend=alt.Legend(orient='bottom')),
        tooltip=['Company', alt.Tooltip('Date:T'),
                 alt.Tooltip('Indexed total return:Q', format='.1f')]
    ).properties(height=380).interactive()
    st.altair_chart(chart, use_container_width=True)

# ------------------------------------------------- valuation history -------
section('Valuation history compared',
        'EV/EBITDA per fiscal year, from annual reported financials and '
        'year-end share prices.')
vh = []
for k in sel:
    for yr, mult in (D['drill'].get(k, {}).get('hist') or []):
        vh.append({'Year': str(yr), 'EV/EBITDA': mult,
                   'Company': svc['names'][k]})
if vh:
    vdf = pd.DataFrame(vh)
    chart = alt.Chart(vdf).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Fiscal year'),
        y=alt.Y('EV/EBITDA:Q', title='EV/EBITDA (×)',
                scale=alt.Scale(zero=False)),
        color=alt.Color('Company:N', scale=alt.Scale(range=SERIES),
                        legend=alt.Legend(orient='bottom')),
        tooltip=['Company', 'Year',
                 alt.Tooltip('EV/EBITDA:Q', format='.1f')]
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)
else:
    st.caption('No valuation history available for the selected companies.')
