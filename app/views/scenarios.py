import json, os
import pandas as pd
import streamlit as st
from components.data import payload, BASIS_BANNER
from components.ui import style_table, df_show, group_header

st.title('Scenario analysis')
st.warning('**Mechanical valuation scenarios — not analyst price targets.** '
           'Implied return decomposes additively into earnings, multiple, '
           'net-debt and share-count effects.')

D = payload()
scr = {r['key']: r for r in D['screener']}
key = st.selectbox('Company', list(scr),
                   format_func=lambda k: f"{D['names'][k]} ({D['tickers'][k]})")
d = D['drill'][key]; r = scr[key]
f = d['fund']; m = d['metrics']

e0 = f.get('ebitda'); m0 = r['ev_ebitda_ltm']; nd0 = m.get('net_debt') or 0
sh0 = f.get('sh'); mino = f.get('minority') or 0; px0 = r['price']
if not all([e0, m0, sh0, px0]):
    st.error('Insufficient inputs for this name (NM denominators).'); st.stop()

c1, c2, c3, c4 = st.columns(4)
de = c1.number_input('Δ EBITDA %', value=0.0, step=5.0) / 100
mt = c2.number_input('Target EV/EBITDA', value=float(m0), step=0.5)
nd = c3.number_input('Net debt (bn, report ccy)', value=round(nd0 / 1e9, 2)) * 1e9
sh = c4.number_input('Shares (m)', value=round(sh0 / 1e6, 1)) * 1e6

e = e0 * (1 + de)
eq0 = m0 * e0 - nd0 - mino
conv = px0 / (eq0 / sh0)              # embeds FX + pence via current-price calibration
eqN = mt * e - nd - mino
px = eqN / sh * conv
ret = px / px0 - 1
earn = m0 * (e - e0) / eq0
mult = (mt - m0) * e / eq0
ndef = -(nd - nd0) / eq0
shef = (eqN / eq0) * (sh0 / sh - 1)

cols = st.columns(6)
for col, (l, v) in zip(cols, [
        ('Implied price', f'{px:,.2f} {r["quote_ccy"]}'),
        ('Implied return', f'{ret * 100:+.1f}%'),
        ('Earnings effect', f'{earn * 100:+.1f}%'),
        ('Multiple effect', f'{mult * 100:+.1f}%'),
        ('Net-debt effect', f'{ndef * 100:+.1f}%'),
        ('Share-count effect', f'{shef * 100:+.1f}%')]):
    col.metric(l, v)
st.caption('EV* = multiple × EBITDA*; Equity* = EV* − net debt − minority; '
           'Price* = Equity*/shares × FX. Effects sum exactly to the return.')

group_header('Preset scenarios')
pres = [json.loads(p) if isinstance(p, str) else p
        for p in [row for row in D['scenarios'] if row['key'] == key]]
df = pd.DataFrame(pres)[['scenario', 'ebitda_report_ccy', 'target_multiple',
                         'implied_ev_bn', 'implied_price', 'current_price',
                         'implied_return_pct', 'earnings_effect_pct',
                         'multiple_effect_pct']]
df.columns = ['Scenario', 'EBITDA (m)', 'Multiple', 'EV (bn)', 'Implied px',
              'Current px', 'Return %', 'Earnings eff. %', 'Multiple eff. %']
df_show(style_table(df, pct_cols=['Return %', 'Earnings eff. %', 'Multiple eff. %'],
                    mult_cols=['Multiple'], num_cols=['EBITDA (m)', 'EV (bn)'],
                    price_cols=['Implied px', 'Current px']),
        height=int(38*(len(df)+1))+4)
st.caption('Bear = −10% EBITDA @ peer Q1 · Base = LTM @ current · Bull = +10% @ '
           'peer Q3 · plus rerating rows. Every row: mechanical scenario, not a target.')
