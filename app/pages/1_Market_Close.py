import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
from components.data import payload, q, ph, BASIS_BANNER

st.set_page_config(page_title='Market Close', page_icon='🏭', layout='wide')
st.title('Market close & peer read-across')
st.caption(BASIS_BANNER)

D = payload()

# True 16:30 UK snapshots (populated by the intraday workflow once enabled)
snaps = q('SELECT key, obs_date, price, later_price FROM eu_close_snapshots '
          'ORDER BY obs_date DESC LIMIT 200')
if snaps:
    latest = snaps[0][1]
    st.success(f'True 16:30 UK benchmark snapshots available (latest {latest}). '
               'Move-since-EU-close uses actual intraday observations.')
    eu = {s[0]: s for s in snaps if s[1] == latest}
else:
    eu = {}
    st.warning('European-close limitation: no intraday snapshots captured yet — '
               'this page shows each market\'s completed full-session move at its '
               'official close (the documented fallback). The intraday GitHub '
               'Actions workflow will populate true 16:30 UK snapshots once enabled.')

subs = ['All'] + [s['name'] for s in D['subgroups']]
pick = st.selectbox('Subgroup', subs)
big = st.checkbox('Big moves only (|1D| > 3%)')

rows = []
for g in D['close_groups']:
    if pick != 'All' and g['subgroup'] != pick:
        continue
    members = [r for r in D['close_rows'] if r['coverage_group'] == g['group']]
    for r in members:
        if big and (r.get('move_1d_pct') is None or abs(r['move_1d_pct']) <= 3):
            continue
        snap = eu.get(r['key'])
        move_since_eu = None
        if snap and snap[2] and snap[3]:
            move_since_eu = (snap[3] / snap[2] - 1) * 100
        rows.append({
            'Group': g['group'], 'Company': ('▮ ' if r['role'] == 'coverage' else '   ') + r['company'],
            'Role': r['role'], 'Ccy': r['ccy'], 'Close': r['close_px'],
            '1D %': r.get('move_1d_pct'), '5D %': r.get('move_5d_pct'),
            '1M %': r.get('move_1m_pct'), '3M %': r.get('move_3m_pct'),
            '12M %': r.get('move_12m_pct'), 'ρ30': r.get('corr30'),
            'vs basket': r.get('rel_vs_basket_pct'),
            'since 16:30 UK %': round(move_since_eu, 2) if move_since_eu is not None else None})
    s = g['stats']
    rows.append({'Group': g['group'], 'Company': f"└ basket: eq {s['eq']:+.2f}% · "
                 f"median {s['median']:+.2f}% · corr-wtd {s['cw']:+.2f}% · "
                 f"β-adj {s['beta_adj']:+.2f}% · best {s['best'][0]} {s['best'][1]:+.2f}%"
                 + (' · ⚠ outlier' if s.get('outlier') else ''),
                 'Role': 'basket'})

df = pd.DataFrame(rows)
def _style(row):
    if row['Role'] == 'coverage':
        return ['background-color: rgba(23,93,99,0.15); font-weight: bold'] * len(row)
    if row['Role'] == 'basket':
        return ['font-style: italic; color: gray'] * len(row)
    return [''] * len(row)
st.dataframe(df.style.apply(_style, axis=1), hide_index=True,
             use_container_width=True, height=650)
st.download_button('Export CSV', df.to_csv(index=False),
                   'capital_goods_market_close_view.csv')
