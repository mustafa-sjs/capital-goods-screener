import os
import pandas as pd
import streamlit as st
from components.data import payload, BASIS_BANNER
from components.ui import style_table, df_show, group_header

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

group_header('EV/EBITDA vs own history (annual, approximate)')
hist = pd.DataFrame(drill['hist'], columns=['year', 'EV/EBITDA'])
if not hist.empty:
    hist['year'] = hist['year'].astype(str)
    st.bar_chart(hist.set_index('year'))
    hs = drill.get('hist_stats') or {}
    st.caption(f"median {hs.get('median'):.1f}× · now {r['ev_ebitda_ltm']}× · "
               f"z-score {r.get('hist_zscore')}")
else:
    st.info('No usable valuation history for this name.')

group_header('Sector-wide dispersion (deduplicated universe)')
hist_all = pd.DataFrame(D['hist'])
if not hist_all.empty:
    hist_all['ev_ebitda'] = pd.to_numeric(hist_all['ev_ebitda'], errors='coerce')
    piv = hist_all.groupby('year')['ev_ebitda'].agg(
        median='median', q1=lambda s: s.quantile(.25), q3=lambda s: s.quantile(.75)).reset_index()
    import altair as alt
    band = alt.Chart(piv).mark_area(opacity=0.18, color='#175d63').encode(
        x=alt.X('year:O', title='fiscal year'), y=alt.Y('q1:Q', title='EV/EBITDA x'),
        y2='q3:Q')
    med = alt.Chart(piv).mark_line(point=True, color='#175d63').encode(
        x='year:O', y='median:Q', tooltip=['year', 'median', 'q1', 'q3'])
    st.altair_chart((band + med).properties(height=300,
        title='Deduplicated pack: median with interquartile band'),
        use_container_width=True)

group_header('Positioning: valuation vs momentum')
pos = pd.DataFrame([{'Company': s['company'],
                     'rel 3M vs peers (pp)': s.get('rel_3m_pct'),
                     'vs peers %': s.get('prem_disc_vs_peers_pct'),
                     'Hist %ile': s.get('hist_percentile'),
                     'Classification': s.get('classification')}
                    for s in D['screener']])
import altair as alt
pts = pos.dropna(subset=['rel 3M vs peers (pp)', 'vs peers %'])
base = alt.Chart(pts).encode(
    x=alt.X('rel 3M vs peers (pp):Q', title='3M relative performance vs peers (pp)'),
    y=alt.Y('vs peers %:Q', title='Premium / discount to peer median (%)'),
    color=alt.Color('Classification:N', legend=alt.Legend(orient='bottom', columns=2)),
    tooltip=['Company', 'vs peers %', 'rel 3M vs peers (pp)', 'Classification'])
chart = (base.mark_circle(size=90, opacity=0.85) +
         base.mark_text(dy=-9, fontSize=9).encode(text='Company:N')
        ).properties(height=420, title='Cheap-and-improving sits bottom-right; '
                     'momentum is context, not a signal direction') +     alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(strokeDash=[4, 4],
                                                  color='#8a9494').encode(y='y:Q')
st.altair_chart(chart, use_container_width=True)
df_show(style_table(pos.sort_values('vs peers %'),
    pct_cols=['vs peers %'], num_cols=['rel 3M vs peers (pp)', 'Hist %ile'],
    class_col='Classification'))
st.caption('Momentum is context, not a signal direction. Return decomposition '
           '(earnings/multiple/net-debt/share-count) lives on the Scenarios page.')
