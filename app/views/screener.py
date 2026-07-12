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
    vst = st.multiselect('Valuation state', sorted(df['valuation_state'].dropna().unique()))
    fst = st.multiselect('Fundamental state', sorted(df['fundamental_state'].dropna().unique()))
    mst = st.multiselect('Momentum state', sorted(df['momentum_state'].dropna().unique()))
    mcap_min = st.number_input('Min mcap $bn', 0.0)
    nd_max = st.number_input('Max ND/EBITDA (0 = any)', 0.0)
    search = st.text_input('Search company / ticker')
    dq_ok = st.checkbox('Hide rows with data-quality flags')

f = df.copy()
if sub: f = f[f['subgroup'].isin(sub)]
if vst: f = f[f['valuation_state'].isin(vst)]
if fst: f = f[f['fundamental_state'].isin(fst)]
if mst: f = f[f['momentum_state'].isin(mst)]
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
        if op == 'in':
            f = f[f[col].isin([v.strip() for v in val.split('|')])]
            continue
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
        'valuation_state': 'Valuation', 'fundamental_state': 'Fundamentals',
        'momentum_state': 'Momentum', 'hist_years': 'Hist n',
        'data_quality': 'Data quality'}
view = f[list(NICE)].rename(columns=NICE).sort_values('vs peers %')
sty = style_table(
    view,
    pct_cols=['vs peers %', 'vs sector %', 'rel 1M', 'rel 3M', 'rel 12M',
              'Dmargin pp', 'Rev g %', '52w dd %', 'FCF yld %', 'Margin %'],
    mult_cols=['EV/EBITDA', 'EV/EBIT', 'P/E', 'Peer med', 'ND/EBITDA'],
    num_cols=['Mcap $bn', 'EV/Rev', 'Hist %ile', 'Hist z'],
    price_cols=['Price'], class_col='Valuation', scale_col='vs peers %')
# also color the other two state columns

df_show(sty, height=640)
with st.expander('Why did these names surface? (component-based, not generated text)'):
    for _, r in f.sort_values('prem_disc_vs_peers_pct').head(12).iterrows():
        bits = []
        if r['prem_disc_vs_peers_pct'] is not None and not pd.isna(r['prem_disc_vs_peers_pct']):
            bits.append(f"{abs(r['prem_disc_vs_peers_pct']):.0f}% "
                        f"{'below' if r['prem_disc_vs_peers_pct']<0 else 'above'} direct-peer median EV/EBITDA "
                        f"({r['ev_ebitda_ltm']}x vs {r['peer_median_ev_ebitda']}x)")
        if r.get('hist_percentile') is not None and not pd.isna(r.get('hist_percentile')):
            bits.append(f"{r['hist_percentile']:.0f}th pct of own range (n={int(r['hist_years'] or 0)}, coarse)")
        if r.get('rel_3m_pct') is not None and not pd.isna(r.get('rel_3m_pct')):
            bits.append(f"3M total-return {r['rel_3m_pct']:+.1f}pp vs peers")
        if r.get('margin_chg_pp') is not None and not pd.isna(r.get('margin_chg_pp')):
            bits.append(f"EBITDA margin {r['margin_chg_pp']:+.1f}pp YoY")
        bits.append(f"momentum: {r['momentum_state']}")
        st.markdown(f"**{r['company']}** — " + '; '.join(bits) + '.')
st.download_button('Export visible rows (CSV)', view.to_csv(index=False),
                   'screener_export.csv')
st.caption(f'{len(f)} of {len(df)} coverage names shown - sorted cheapest-vs-'
           'peers first - colour scale on "vs peers %": green = discount, '
           'red = premium - NM = denominator missing, never zero-filled.')
