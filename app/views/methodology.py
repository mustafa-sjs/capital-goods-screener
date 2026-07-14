"""Methodology — every definition in one place, out of the way of the
research workflow but never hidden."""
import os, sys

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from components.data import BASIS_HELP
from components.ui import page_header, section, df_show
from src.utils import metrics as M
from src.features.momentum import momentum_config

page_header('Methodology',
            'What every number means, how it is calculated, and the known '
            'limitations.')

section('Data basis')
st.markdown(BASIS_HELP)
st.markdown(
    '- **Prices** — daily closes from Yahoo Finance\'s public endpoint, '
    'validated and stored as a canonical history with raw, split-adjusted '
    'and total-return (dividends reinvested) series.\n'
    '- **Financials** — latest reported full periods (FactIQ statements and '
    'SEC XBRL). No consensus estimates exist in the pipeline, so nothing is '
    'presented as a forecast.\n'
    '- **Historical valuation** — fiscal-year fundamentals × year-end share '
    'price: approximate by construction and labelled as such.\n'
    '- **Returns** — displayed price moves use the raw basis (market '
    'convention); relative and trend comparisons use the total-return basis '
    '(a dividend is not a price crash).')

section('Price trend definitions')
cfg = momentum_config()
dp = cfg['ewma']['default_pair']
st.markdown(
    f'Price trends use two exponentially weighted moving averages (EWMAs) '
    f'of the total-return price — a fast one and a slow one. The default '
    f'setting is **{dp[0]}/{dp[1]} days**, the best-tested combination out '
    f'of sample. Three separate fields describe the state:\n\n'
    f'- **Trend** — Uptrend when the fast average is above the slow one, '
    f'Downtrend when below, No clear trend when there is too little '
    f'history.\n'
    f'- **Momentum change** — Strengthening / Stable / Weakening: whether '
    f'the distance between the two averages widened or narrowed over the '
    f'last five sessions.\n'
    f'- **Recent signal** — New positive/negative crossover if the averages '
    f'crossed within the last 15 sessions and the new direction still '
    f'holds; otherwise no recent crossover.\n\n'
    f'**Honesty note:** in the backtest no EWMA setting beat buy-and-hold '
    f'out of sample after costs — trend timing mainly reduced drawdowns. '
    f'Historical-evidence columns (e.g. how often a positive 3-month return '
    f'followed similar signals) always state their sample size.')

section('Metric dictionary')
cat_names = {'identity': 'Identity', 'valuation': 'Valuation',
             'fundamentals': 'Fundamentals', 'performance': 'Performance',
             'trend': 'Price trend', 'risk': 'Risk', 'quality': 'Data quality'}
rows = []
for mid, d in M.METRIC_DEFINITIONS.items():
    rows.append({'Metric': d['display_name'],
                 'Category': cat_names.get(d['category'], d['category']),
                 'Definition': d['description']})
df = pd.DataFrame(rows).sort_values(['Category', 'Metric'])
cat = st.multiselect('Category', sorted(df['Category'].unique()))
if cat:
    df = df[df['Category'].isin(cat)]
df_show(df, height=520, pinned=('Metric',))
st.download_button('Download definitions (CSV)', df.to_csv(index=False),
                   'metric_definitions.csv')

section('Momentum score weights')
st.json(cfg['score']['weights'])
st.caption('The 0–100 momentum rank score is a transparent weighted sum of '
           'percentile ranks within the selected universe — never a black '
           'box.')

section('Full methodology documents')
DOCS = [('docs/methodology.md', 'Platform methodology'),
        ('docs/momentum_methodology.md', 'Momentum methodology'),
        ('docs/data_dictionary.md', 'Data dictionary'),
        ('capital_goods_methodology.md', 'Metric-level methodology notes')]
for path, title in DOCS:
    p = os.path.join(ROOT, path)
    if os.path.exists(p):
        with st.expander(title):
            st.markdown(open(p).read())
