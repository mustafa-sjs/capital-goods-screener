import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
from components.data import payload, BASIS_BANNER

st.set_page_config(page_title='Sector Rerating', page_icon='🏭', layout='wide')
st.title('Sector rerating & performance')
st.caption(BASIS_BANNER + ' History = fiscal-year fundamentals × year-end price '
           '(approximate — no point-in-time consensus vintages exist).')

D = payload()
scr = {r['key']: r for r in D['screener']}
names = {k: D['names'][k] for k in scr}
key = st.selectbox('Coverage company', list(scr),
                   format_func=lambda k: f"{names[k]} ({D['tickers'][k]})")
drill = D['drill'][key]
r = scr[key]

c1, c2, c3, c4 = st.columns(4)
c1.metric('EV/EBITDA (LTM)', f"{r['ev_ebitda_ltm']}×" if r['ev_ebitda_ltm'] else 'NM')
c2.metric('vs direct peers', f"{r['prem_disc_vs_peers_pct']:+.1f}%"
          if r['prem_disc_vs_peers_pct'] is not None else '–')
c3.metric('vs sector', f"{r['prem_disc_vs_sector_pct']:+.1f}%"
          if r['prem_disc_vs_sector_pct'] is not None else '–')
c4.metric('Own-history percentile', f"{r['hist_percentile']:.0f}"
          if r.get('hist_percentile') is not None else '–',
          help=f"{r.get('hist_years')} annual observations — coarse")

st.subheader('EV/EBITDA vs own history (annual, approximate)')
hist = pd.DataFrame(drill['hist'], columns=['year', 'EV/EBITDA'])
if not hist.empty:
    hist['year'] = hist['year'].astype(str)
    st.bar_chart(hist.set_index('year'))
    hs = drill.get('hist_stats') or {}
    st.caption(f"median {hs.get('median'):.1f}× · now {r['ev_ebitda_ltm']}× · "
               f"z-score {r.get('hist_zscore')}")
else:
    st.info('No usable valuation history for this name.')

st.subheader('Sector-wide dispersion (deduplicated universe)')
hist_all = pd.DataFrame(D['hist'])
if not hist_all.empty:
    hist_all['ev_ebitda'] = pd.to_numeric(hist_all['ev_ebitda'], errors='coerce')
    piv = hist_all.groupby('year')['ev_ebitda'].agg(
        median='median', q1=lambda s: s.quantile(.25), q3=lambda s: s.quantile(.75))
    st.line_chart(piv)

st.subheader('Positioning: valuation vs momentum')
pos = pd.DataFrame([{'Company': s['company'],
                     'rel 3M vs peers (pp)': s.get('rel_3m_pct'),
                     'vs peers %': s.get('prem_disc_vs_peers_pct'),
                     'Hist %ile': s.get('hist_percentile'),
                     'Classification': s.get('classification')}
                    for s in D['screener']])
st.scatter_chart(pos.dropna(subset=['rel 3M vs peers (pp)', 'vs peers %']),
                 x='rel 3M vs peers (pp)', y='vs peers %')
st.dataframe(pos.sort_values('vs peers %'), hide_index=True, use_container_width=True)
st.caption('Momentum is context, not a signal direction. Return decomposition '
           '(earnings/multiple/net-debt/share-count) lives on the Scenarios page.')
