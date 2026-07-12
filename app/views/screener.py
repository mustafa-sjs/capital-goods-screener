import json, os
import pandas as pd
import streamlit as st
import yaml
from components.data import payload, BASIS_BANNER
from components.ui import style_table, df_show

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
st.title('Screener — valuation, quality, performance')
st.caption(BASIS_BANNER + ' Every multiple is **LTM reported** (uniform basis). '
           'No opaque master score — every column is a defined metric; presets '
           'are editable YAML rules.')

D = payload()
df = pd.DataFrame(D['screener'])

presets = {}
ppath = os.path.join(ROOT, 'config', 'screen_presets.yaml')
if os.path.exists(ppath):
    presets = yaml.safe_load(open(ppath)) or {}

with st.sidebar:
    st.header('Filters')
    preset = st.selectbox('Preset', ['None'] + list(presets))
    sub = st.multiselect('Subgroup', sorted(df['subgroup'].unique()))
    cls = st.multiselect('Classification', sorted(df['classification'].dropna().unique()))
    mcap_min = st.number_input('Min mcap $bn', 0.0)
    nd_max = st.number_input('Max ND/EBITDA (0 = any)', 0.0)
    search = st.text_input('Search company / ticker')
    dq_ok = st.checkbox('Hide rows with data-quality flags')

f = df.copy()
if sub: f = f[f['subgroup'].isin(sub)]
if cls: f = f[f['classification'].isin(cls)]
if mcap_min: f = f[f['mcap_usd_bn'].fillna(0) >= mcap_min]
if nd_max: f = f[f['nd_ebitda'].fillna(0) <= nd_max]
if search:
    s = search.lower()
    f = f[f['company'].str.lower().str.contains(s) |
          f['ticker'].str.lower().str.contains(s)]
if dq_ok: f = f[f['data_quality'] == 'OK']

if preset != 'None' and preset in presets:
    rules = presets[preset].get('rules', {})
    st.info(f"**{preset.replace('_',' ').title()}** — "
            f"{presets[preset].get('description','')}  \n"
            f"Rules: `{json.dumps(rules)}`")
    for col, rule in rules.items():
        if col not in f.columns:
            continue
        op, val = rule.split(' ', 1)
        val = float(val)
        f = f[f[col].notna()]
        f = f[f[col] <= val] if op == '<=' else (f[f[col] >= val] if op == '>=' else f)

NICE = {'company': 'Company', 'ticker': 'Ticker', 'price': 'Price',
        'quote_ccy': 'Ccy', 'mcap_usd_bn': 'Mcap $bn',
        'ev_ebitda_ltm': 'EV/EBITDA', 'prem_disc_vs_peers_pct': 'vs peers %',
        'peer_median_ev_ebitda': 'Peer med', 'prem_disc_vs_sector_pct': 'vs sector %',
        'hist_percentile': 'Hist %ile', 'hist_zscore': 'Hist z',
        'ev_ebit_ltm': 'EV/EBIT', 'pe_ltm': 'P/E', 'ev_rev_ltm': 'EV/Rev',
        'fcf_yield_pct': 'FCF yld %', 'rev_growth_pct': 'Rev g %',
        'ebitda_margin_pct': 'Margin %', 'margin_chg_pp': 'Dmargin pp',
        'nd_ebitda': 'ND/EBITDA', 'rel_1m_pct': 'rel 1M', 'rel_3m_pct': 'rel 3M',
        'rel_12m_pct': 'rel 12M', 'drawdown_52w_pct': '52w dd %',
        'classification': 'Classification', 'data_quality': 'Data quality'}
view = f[list(NICE)].rename(columns=NICE).sort_values('vs peers %')
sty = style_table(
    view,
    pct_cols=['vs peers %', 'vs sector %', 'rel 1M', 'rel 3M', 'rel 12M',
              'Dmargin pp', 'Rev g %', '52w dd %', 'FCF yld %', 'Margin %'],
    mult_cols=['EV/EBITDA', 'EV/EBIT', 'P/E', 'Peer med', 'ND/EBITDA'],
    num_cols=['Mcap $bn', 'EV/Rev', 'Hist %ile', 'Hist z'],
    price_cols=['Price'], class_col='Classification', scale_col='vs peers %')
df_show(sty, height=640)
st.download_button('Export visible rows (CSV)', view.to_csv(index=False),
                   'screener_export.csv')
st.caption(f'{len(f)} of {len(df)} coverage names shown - sorted cheapest-vs-'
           'peers first - colour scale on "vs peers %": green = discount, '
           'red = premium - NM = denominator missing, never zero-filled.')
