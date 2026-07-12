import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
import pandas as pd
from components.data import (payload, last_run, latest_snapshot, q, ph,
                             fmt_pct, BASIS_BANNER)

st.set_page_config(page_title='Capital Goods — Research Platform',
                   page_icon='🏭', layout='wide')
st.title('Capital Goods — Coverage Platform')
st.caption(BASIS_BANNER)

D = payload()
run = last_run()
c1, c2, c3, c4 = st.columns(4)
c1.metric('Data as of', D.get('generated', '?') + ' close')
c2.metric('Last refresh', str(run[2])[:16] if run else 'never',
          delta=None, help=run[4] if run else None)
c3.metric('Refresh status', (run[3] or '?') if run else '?')
c4.metric('Coverage / securities',
          f"{len(D.get('screener', []))} / {len(D.get('names', {}))}")
if run and run[3] == 'failed':
    st.error(f'Last refresh FAILED — see Admin page. Notes: {run[4]}')

st.subheader('Biggest moves at the last close')
rows = sorted([r for r in D['close_rows'] if r.get('move_1d_pct') is not None],
              key=lambda r: abs(r['move_1d_pct']), reverse=True)[:10]
st.dataframe(pd.DataFrame([{
    'Company': r['company'], 'Role': r['role'], '1D %': r['move_1d_pct'],
    '3M %': r.get('move_3m_pct'), '12M %': r.get('move_12m_pct')} for r in rows]),
    hide_index=True, use_container_width=True)

col_l, col_r = st.columns(2)
with col_l:
    st.subheader('Largest valuation dislocations vs direct peers')
    sc = sorted([r for r in D['screener'] if r.get('prem_disc_vs_peers_pct') is not None],
                key=lambda r: r['prem_disc_vs_peers_pct'])
    df = pd.DataFrame([{'Company': r['company'],
                        'EV/EBITDA': r['ev_ebitda_ltm'],
                        'vs peers %': r['prem_disc_vs_peers_pct'],
                        'Classification': r['classification']}
                       for r in sc[:5] + sc[-5:]])
    st.dataframe(df, hide_index=True, use_container_width=True)
with col_r:
    st.subheader('What changed since the previous snapshot')
    snap = latest_snapshot()
    ev = q(f'SELECT key, event_type, detail FROM daily_change_events '
           f'WHERE snapshot_date = {ph()} ORDER BY event_type', [snap]) if snap else []
    if ev:
        st.dataframe(pd.DataFrame(ev, columns=['Key', 'Event', 'Detail']),
                     hide_index=True, use_container_width=True)
    else:
        st.info('No change events vs the previous snapshot (or first snapshot).')

st.subheader('Momentum context (revisions substitute)')
st.caption('No consensus feed exists — momentum = relative price performance '
           'and reported growth, never fabricated revisions.')
mo = sorted([r for r in D['screener'] if r.get('rel_3m_pct') is not None],
            key=lambda r: r['rel_3m_pct'])
c1, c2 = st.columns(2)
c1.write('**Weakest 3M vs peers**')
c1.dataframe(pd.DataFrame([{'Company': r['company'], 'rel 3M pp': r['rel_3m_pct']}
                           for r in mo[:5]]), hide_index=True)
c2.write('**Strongest 3M vs peers**')
c2.dataframe(pd.DataFrame([{'Company': r['company'], 'rel 3M pp': r['rel_3m_pct']}
                           for r in mo[-5:][::-1]]), hide_index=True)

st.subheader('Data-quality & stale warnings')
warn = q("""SELECT check_name, severity, subject, message FROM validation_results
            WHERE severity IN ('warning','error','critical')
            ORDER BY created_at DESC LIMIT 10""")
if warn:
    st.dataframe(pd.DataFrame(warn, columns=['Check', 'Severity', 'Subject', 'Message']),
                 hide_index=True, use_container_width=True)
else:
    st.success('No open validation warnings.')

st.caption('Free-Tier Usage: see Admin & Status page — target platform cost $0/month.')
