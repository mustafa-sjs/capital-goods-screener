import os, sys
import numpy as np
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from components.data import payload, BASIS_BANNER
from components.ui import style_table, df_show, group_header
from src.features.momentum import momentum_config
from src.screening.momentum import (build_table, heatmap_frame, HEATMAP_COLS,
                                    backtest_payload)

st.title('Momentum')
st.caption('EWMA-signal screener on **total-return adjusted** prices (10y '
           'canonical history). Historical evidence is measured, not '
           'promised: out-of-sample, cost-aware, sample sizes shown. '
           'Not investment advice.')

D = payload()
cfg = momentum_config()
bt = backtest_payload()
names = D['names']
sub_of, peers_of = {}, {}
for sg in D['subgroups']:
    for g in sg['groups']:
        for k in g['coverage'] + g['peers']:
            sub_of.setdefault(k, sg['name'])
            peers_of.setdefault(k, g['peers'])


@st.cache_data(ttl=900, show_spinner='Computing momentum cross-section...')
def _table(pair, confirm):
    return build_table(sorted(names), names, sub_of, peers_of, pair, confirm)


# ---- 1) compact filter bar -------------------------------------------------
pairs = [tuple(p) for p in cfg['ewma']['pairs']]
default_pair = tuple(cfg['ewma']['default_pair'])
if 'mom_pair' not in st.session_state:
    st.session_state['mom_pair'] = default_pair
c1, c2, c3, c4, c5, c6 = st.columns([1.4, 1.4, 1.2, 1.3, 1.3, 0.9])
sub = c1.multiselect('Subgroup', sorted(set(sub_of.values())))
search = c2.text_input('Search company')
pair = c3.selectbox('EWMA pair', pairs,
                    index=pairs.index(st.session_state['mom_pair']),
                    format_func=lambda p: f'{p[0]}/{p[1]}'
                    + (' (robust default)' if p == default_pair else ''))
sigf = c4.selectbox('Signal', ['All', 'Bullish', 'Bearish',
                               'New bullish crossover', 'New bearish crossover'])
clsf = c5.multiselect('Classification',
                      ['strong', 'improving', 'neutral', 'deteriorating', 'weak'])
topn = c6.number_input('Top N', 5, 79, 79, step=5)

df = _table(pair, 5)
f = df.copy()
if sub: f = f[f['subgroup'].isin(sub)]
if search:
    f = f[f['company'].str.lower().str.contains(search.lower())]
if sigf == 'Bullish': f = f[f['signal'] == 'bullish']
elif sigf == 'Bearish': f = f[f['signal'] == 'bearish']
elif sigf == 'New bullish crossover':
    f = f[(f['cross_type'] == 'bullish') & (f['days_since_cross'] <= 15)]
elif sigf == 'New bearish crossover':
    f = f[(f['cross_type'] == 'bearish') & (f['days_since_cross'] <= 15)]
if clsf: f = f[f['classification'].isin(clsf)]
f = f.head(int(topn))

# ---- 2) summary cards ------------------------------------------------------
newb = int(((df['cross_type'] == 'bullish') & (df['days_since_cross'] <= 15)).sum())
newx = int(((df['cross_type'] == 'bearish') & (df['days_since_cross'] <= 15)).sum())
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric('Screened', len(f))
k2.metric('Bullish signals', int((df['signal'] == 'bullish').sum()))
k3.metric('New bullish (≤15d)', newb)
k4.metric('New bearish (≤15d)', newx)
if bt:
    ud = bt['universe_default']
    k5.metric('Robust pair (OOS)', f"{ud['pair'][0]}/{ud['pair'][1]} c{ud['confirm']}")
    fw = bt['forward_returns_winner'].get('60') or bt['forward_returns_winner'].get(60, {})
    k6.metric('Hist. positive 60d rate', f"{fw.get('pos_rate_pct', '–')}%",
              help=f"share of confirmed bullish crossovers followed by a positive "
                   f"60-session TR return (n={fw.get('n', '?')}). Historical, not predictive.")
if bt:
    st.caption(f"⚠ **Honest caveat from the backtest ({bt['generated'][:10]}):** no "
               f"EWMA pair beat buy-and-hold out of sample in 2022-26 (excess "
               f"{bt['ranked'][0]['oos']['excess_ann_pct']}% for the best pair) — timing "
               f"reduced drawdowns (max {bt['ranked'][0]['oos']['max_drawdown_pct']}%) "
               f"but cost return in a strong bull market. Crossovers remain useful "
               f"entry markers (see expander). Costs: "
               f"{bt['config']['cost_bps'] + bt['config']['slippage_bps']}bps/side, "
               f"next-close execution.")

# ---- 3) heatmap + ranked table ---------------------------------------------
group_header('Momentum heatmap (cross-sectional percentiles)')
hm = heatmap_frame(f)
import altair as alt
hm_long = hm.reset_index().melt('company', var_name='metric', value_name='pctile')
raw_long = f[['company'] + HEATMAP_COLS].melt('company', var_name='metric',
                                              value_name='raw')
hm_long = hm_long.merge(raw_long, on=['company', 'metric'])
order = f['company'].tolist()
chart = alt.Chart(hm_long).mark_rect().encode(
    x=alt.X('metric:N', sort=HEATMAP_COLS, title=None),
    y=alt.Y('company:N', sort=order, title=None),
    color=alt.Color('pctile:Q', scale=alt.Scale(scheme='redyellowgreen',
                                                domain=[0, 100]),
                    legend=alt.Legend(title='pctile')),
    tooltip=['company', 'metric', alt.Tooltip('raw:Q', format='.1f'),
             alt.Tooltip('pctile:Q', format='.0f')]
).properties(height=max(220, 16 * len(f)))
st.altair_chart(chart, use_container_width=True)

group_header('Ranked momentum screener')
NICE = {'rank': 'Rank', 'company': 'Company', 'key': 'Key', 'subgroup': 'Subgroup',
        'ret_1m': '1M %', 'ret_3m': '3M %', 'ret_6m': '6M %', 'ret_12m': '12M %',
        'rel_strength': 'Rel str 12M', 'spread': 'EWMA spread %',
        'signal': 'Signal', 'cross_date': 'Cross date',
        'days_since_cross': 'Days since', 'pos_3m_rate': 'Hist +3M rate %',
        'n_signals': 'Signals n', 'momentum_score': 'Score'}
view = f[list(NICE)].rename(columns=NICE)
sty = style_table(view,
                  pct_cols=['1M %', '3M %', '6M %', '12M %', 'Rel str 12M',
                            'EWMA spread %'],
                  num_cols=['Rank', 'Days since', 'Hist +3M rate %', 'Signals n',
                            'Score'],
                  class_col='Signal', scale_col='Score')
df_show(sty, height=min(600, 38 * (len(view) + 1)))
st.download_button('Export CSV', view.to_csv(index=False), 'momentum_screen.csv')

# ---- 4) selected-company detail ---------------------------------------------
group_header('Company detail')
sel = st.selectbox('Company', f['key'].tolist(),
                   format_func=lambda k: names.get(k, k))
row = df[df['key'] == sel].iloc[0]
import plotly.graph_objects as go
hp = pd.read_parquet(os.path.join(ROOT, 'data', 'history', 'prices_daily.parquet'))
hp = hp[hp.key == sel].sort_values('session_date')
px = pd.Series(hp['close_tr'].values, index=pd.to_datetime(hp['session_date']),
               dtype='float64')
fast = px.ewm(span=pair[0], adjust=False, min_periods=pair[0]).mean()
slow = px.ewm(span=pair[1], adjust=False, min_periods=pair[1]).mean()
state = (fast > slow).astype(int).where(fast.notna() & slow.notna())
crosses = state.diff()
log_y = st.toggle('Log scale')
fig = go.Figure()
fig.add_scatter(x=px.index, y=px, name='TR price', line=dict(color='#175d63', width=1.4))
fig.add_scatter(x=fast.index, y=fast, name=f'EMA {pair[0]}',
                line=dict(color='#2a78d6', width=1))
fig.add_scatter(x=slow.index, y=slow, name=f'EMA {pair[1]}',
                line=dict(color='#eda100', width=1))
bx = crosses[crosses == 1].index
sx = crosses[crosses == -1].index
fig.add_scatter(x=bx, y=px.reindex(bx), mode='markers', name='bullish cross',
                marker=dict(symbol='triangle-up', size=10, color='#0a7d38'))
fig.add_scatter(x=sx, y=px.reindex(sx), mode='markers', name='bearish cross',
                marker=dict(symbol='triangle-down', size=10, color='#c0392b'))
fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                  yaxis_type='log' if log_y else 'linear',
                  legend=dict(orientation='h', y=1.08),
                  xaxis=dict(rangeselector=dict(buttons=[
                      dict(count=1, label='1y', step='year'),
                      dict(count=3, label='3y', step='year'),
                      dict(count=5, label='5y', step='year'),
                      dict(step='all')])))
st.plotly_chart(fig, use_container_width=True)

p1, p2, p3, p4, p5 = st.columns(5)
p1.metric('Signal', row['signal'] or '–',
          help=f"cross {row['cross_date']} ({row['days_since_cross']} sessions ago)")
p2.metric('EWMA spread', f"{row['spread']}%" if row['spread'] is not None else '–')
p3.metric('Score', f"{row['momentum_score']:.0f}" if pd.notna(row['momentum_score']) else '–')
p4.metric('Hist +3M rate', f"{row['pos_3m_rate']}%" if row['pos_3m_rate'] else '–',
          help=f"n={row['n_signals']} prior confirmed bullish crossovers for this pair")
p5.metric('Median 3M fwd', f"{row['median_3m_fwd']}%" if row['median_3m_fwd'] else '–')
with st.expander('Score components (transparent weights from config/momentum.yaml)'):
    comp_cols = [c for c in df.columns if c.endswith('_pctile')]
    st.dataframe(df[df['key'] == sel][comp_cols].T.rename(columns={df[df['key'] == sel].index[0]: 'percentile'}),
                 use_container_width=True)
    st.json(cfg['score']['weights'])

# ---- collapsed backtest expander ---------------------------------------------
with st.expander('Historical EWMA strategy comparison (out-of-sample ranked)'):
    if not bt:
        st.info('Run `python scripts/backtest_momentum.py` to generate results.')
    else:
        rows = []
        for i, r in enumerate(bt['ranked'][:5], 1):
            o = r['oos']
            rows.append({'Rank': i, 'Fast': r['pair'][0], 'Slow': r['pair'][1],
                         'Confirm d': r['confirm'],
                         'OOS ann %': o['ann_return_pct'],
                         'OOS excess %': o['excess_ann_pct'],
                         'OOS Sharpe': o['sharpe'],
                         'Max DD %': o['max_drawdown_pct'],
                         'Trades': o['n_trades'], 'Win %': o['win_rate_pct'],
                         'Stability': r['stability']})
        df_show(pd.DataFrame(rows))
        pick = st.selectbox('Apply pair from table', ['—'] + [
            f"{r['pair'][0]}/{r['pair'][1]}" for r in bt['ranked'][:5]])
        if pick != '—':
            fp, sp = map(int, pick.split('/'))
            if (fp, sp) != st.session_state['mom_pair']:
                st.session_state['mom_pair'] = (fp, sp)
                st.rerun()
        full = pd.json_normalize(bt['ranked'])
        st.download_button('Full results CSV', full.to_csv(index=False),
                           'momentum_backtest_full.csv')
        st.caption('Chronological 60/40 in-sample/out-of-sample split; '
                   'next-close execution; 25bps/side all-in costs. Universe is '
                   'today\'s coverage (survivorship bias — stated limitation). '
                   'Historically strongest ≠ guaranteed optimal.')
