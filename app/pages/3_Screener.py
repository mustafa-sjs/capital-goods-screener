import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
import yaml
from components.data import payload, BASIS_BANNER

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
st.set_page_config(page_title='Screener', page_icon='🏭', layout='wide')
st.title('Screener — valuation, quality, performance')
st.caption(BASIS_BANNER + ' No opaque master score: every column is a '
           'transparent, defined metric; presets are editable YAML rules.')

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
    search = st.text_input('Search company/ticker')
    dq_ok = st.checkbox('Hide rows with data-quality flags')

f = df.copy()
if sub: f = f[f['subgroup'].isin(sub)]
if cls: f = f[f['classification'].isin(cls)]
if mcap_min: f = f[f['mcap_usd_bn'].fillna(0) >= mcap_min]
if nd_max: f = f[f['nd_ebitda'].fillna(0) <= nd_max]
if search:
    s = search.lower()
    f = f[f['company'].str.lower().str.contains(s) | f['ticker'].str.lower().str.contains(s)]
if dq_ok: f = f[f['data_quality'] == 'OK']

if preset != 'None' and preset in presets:
    rules = presets[preset].get('rules', {})
    st.info(f"**{preset}** — {presets[preset].get('description','')}  \n"
            f"Rules: `{json.dumps(rules)}` (edit in config/screen_presets.yaml)")
    for col, rule in rules.items():
        if col not in f.columns:
            continue
        op, val = rule.split(' ', 1)
        val = float(val)
        f = f[f[col].notna()]
        f = f[f[col] <= val] if op == '<=' else (f[f[col] >= val] if op == '>=' else f)

cols = ['coverage_group', 'company', 'ticker', 'price', 'quote_ccy', 'mcap_usd_bn',
        'estimate_basis', 'ev_ebitda_ltm', 'ev_ebit_ltm', 'pe_ltm', 'ev_rev_ltm',
        'fcf_yield_pct', 'peer_median_ev_ebitda', 'prem_disc_vs_peers_pct',
        'prem_disc_vs_sector_pct', 'hist_percentile', 'hist_zscore', 'rev_growth_pct',
        'ebitda_margin_pct', 'margin_chg_pp', 'nd_ebitda', 'rel_1m_pct', 'rel_3m_pct',
        'rel_12m_pct', 'drawdown_52w_pct', 'classification', 'data_quality']
st.dataframe(f[cols].sort_values('prem_disc_vs_peers_pct'),
             hide_index=True, use_container_width=True, height=600)
st.download_button('Export visible rows (CSV)', f[cols].to_csv(index=False),
                   'screener_export.csv')
st.caption(f'{len(f)} of {len(df)} coverage names shown. Estimate basis is '
           'uniform LTM; the forward toggle activates automatically if a '
           'consensus source is ever added.')
