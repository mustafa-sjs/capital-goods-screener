import pandas as pd
import streamlit as st
from components.data import payload, q, BASIS_BANNER, data_version
from components.ui import group_header, basket_caption, style_table, df_show

st.title('Market close & peer read-across')
st.caption(BASIS_BANNER)

D = payload(data_version())
snaps = q('SELECT key, obs_date, price, later_price FROM eu_close_snapshots '
          'ORDER BY obs_date DESC LIMIT 300')
if snaps:
    latest = snaps[0][1]
    eu = {s[0]: s for s in snaps if s[1] == latest}
    st.success(f'True 16:30 UK benchmark snapshots active (latest {latest}) — '
               'the "since 16:30 UK" column uses actual intraday observations.')
else:
    eu = {}
    st.warning('No intraday snapshots yet — showing each market\'s completed '
               'full-session move at its official close (documented fallback). '
               'The intraday workflow populates true 16:30 UK snapshots.')

c1, c2 = st.columns([2, 1])
subs = ['All subgroups'] + [s['name'] for s in D['subgroups']]
pick = c1.selectbox('Subgroup', subs, label_visibility='collapsed')
big = c2.checkbox('Big moves only (|1D| > 3%)')

MOVES = ['1D %', '5D %', '1M %', '3M %', '12M %', 'vs basket']
for g in D['close_groups']:
    if pick != 'All subgroups' and g['subgroup'] != pick:
        continue
    members = [r for r in D['close_rows'] if r['coverage_group'] == g['group']]
    rows = []
    for r in members:
        if big and (r.get('move_1d_pct') is None or abs(r['move_1d_pct']) <= 3):
            continue
        snap = eu.get(r['key'])
        since_eu = ((snap[3] / snap[2] - 1) * 100
                    if snap and snap[2] and snap[3] else None)
        rows.append({
            'Company': ('▮ ' if r['role'] == 'coverage' else ' ') + r['company'],
            'Ticker': r['ticker'], 'Ccy': r['ccy'], 'Close': r['close_px'],
            '1D %': r.get('move_1d_pct'), '5D %': r.get('move_5d_pct'),
            '1M %': r.get('move_1m_pct'), '3M %': r.get('move_3m_pct'),
            '12M %': r.get('move_12m_pct'), 'ρ30': r.get('corr30'),
            'vs basket': r.get('rel_vs_basket_pct'),
            'since 16:30 UK': since_eu})
    if not rows:
        continue
    df = pd.DataFrame(rows)
    bold = {i for i, r in enumerate(rows) if r['Company'].startswith('▮')}
    group_header(g['group'], g['subgroup'])
    sty = style_table(df, pct_cols=MOVES + ['since 16:30 UK'],
                      price_cols=['Close'], num_cols=['ρ30'], bold_rows=bold)
    df_show(sty)
    basket_caption(g['stats'])

st.caption('▮ = coverage company (bold row) · peers indented beneath · ρ30 = '
           '30-day correlation of daily log returns vs the coverage name · '
           '"vs basket" = 1D move minus basket equal-weighted move.')
