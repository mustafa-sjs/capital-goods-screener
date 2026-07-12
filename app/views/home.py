import pandas as pd
import streamlit as st
from components.data import (payload, last_run, latest_snapshot, q, ph,
                             BASIS_BANNER)
from components.ui import style_table, df_show, status_badge, group_header

st.title('Capital Goods — Coverage Platform')
st.caption(BASIS_BANNER)

D = payload()
run = last_run()
c1, c2, c3, c4 = st.columns(4)
c1.metric('Data as of', f"{D.get('generated', '?')} close")
c2.metric('Coverage / unique securities',
          f"{len(D.get('screener', []))} / {len(D.get('names', {}))}",
          help='114 peer-basket slots; repeated peers deduplicate to 79 unique securities')
c3.metric('Last refresh', str(run[2])[:16] if run else 'never')
with c4:
    st.markdown('<div style="font-size:12px;color:#8a9494;margin-bottom:2px">'
                'Refresh status</div>', unsafe_allow_html=True)
    kind = {'success': 'ok', 'partial': 'warn'}.get(run[3] if run else '', 'bad')
    status_badge((run[3] or 'unknown').upper() if run else 'NO RUNS', kind)
if run and run[3] == 'failed':
    st.error(f'Last refresh FAILED — see Admin & Status. Notes: {run[4]}')

left, right = st.columns(2)
with left:
    group_header('Biggest moves at the last close')
    rows = sorted([r for r in D['close_rows'] if r.get('move_1d_pct') is not None],
                  key=lambda r: abs(r['move_1d_pct']), reverse=True)[:8]
    df = pd.DataFrame([{'Company': r['company'],
                        'Role': r['role'], '1D %': r['move_1d_pct'],
                        '3M %': r.get('move_3m_pct'), '12M %': r.get('move_12m_pct')}
                       for r in rows])
    df_show(style_table(df, pct_cols=['1D %', '3M %', '12M %']))
with right:
    group_header('What changed since the previous snapshot')
    snap = latest_snapshot()
    ev = q(f'SELECT key, event_type, detail FROM daily_change_events '
           f'WHERE snapshot_date = {ph()} ORDER BY event_type', [snap]) if snap else []
    if ev:
        df_show(pd.DataFrame(ev, columns=['Key', 'Event', 'Detail']))
    else:
        st.info('No change events vs the previous snapshot — events accumulate '
                'as daily snapshots build up.')

left2, right2 = st.columns(2)
with left2:
    group_header('Largest discounts vs direct peers')
    sc = sorted([r for r in D['screener'] if r.get('prem_disc_vs_peers_pct') is not None],
                key=lambda r: r['prem_disc_vs_peers_pct'])
    df = pd.DataFrame([{'Company': r['company'], 'EV/EBITDA': r['ev_ebitda_ltm'],
                        'vs peers %': r['prem_disc_vs_peers_pct'],
                        'Momentum': r.get('momentum_state')} for r in sc[:6]])
    df_show(style_table(df, pct_cols=['vs peers %'], mult_cols=['EV/EBITDA'],
                        class_col='Momentum'))
with right2:
    group_header('Largest premiums vs direct peers')
    prem_only = [r for r in sc if r['prem_disc_vs_peers_pct'] > 0][-6:][::-1]
    df = pd.DataFrame([{'Company': r['company'], 'EV/EBITDA': r['ev_ebitda_ltm'],
                        'vs peers %': r['prem_disc_vs_peers_pct'],
                        'Momentum': r.get('momentum_state')} for r in prem_only])
    df_show(style_table(df, pct_cols=['vs peers %'], mult_cols=['EV/EBITDA'],
                        class_col='Momentum'))

group_header('Momentum context (revisions substitute)')
st.caption('No consensus feed exists — momentum = relative price performance '
           'and reported growth, never fabricated revisions.')
mo = sorted([r for r in D['screener'] if r.get('rel_3m_pct') is not None],
            key=lambda r: r['rel_3m_pct'])
m1, m2 = st.columns(2)
with m1:
    st.markdown('**Weakest 3M vs peer basket**')
    df_show(style_table(pd.DataFrame(
        [{'Company': r['company'], 'rel 3M pp': r['rel_3m_pct'],
          'Rev g %': r.get('rev_growth_pct')} for r in mo[:5]]),
        pct_cols=['rel 3M pp', 'Rev g %']))
with m2:
    st.markdown('**Strongest 3M vs peer basket**')
    df_show(style_table(pd.DataFrame(
        [{'Company': r['company'], 'rel 3M pp': r['rel_3m_pct'],
          'Rev g %': r.get('rev_growth_pct')} for r in mo[-5:][::-1]]),
        pct_cols=['rel 3M pp', 'Rev g %']))

warn = q("""SELECT check_name, severity, subject, min(created_at), max(created_at),
            count(*) FROM validation_results
            WHERE severity IN ('warning','error','critical')
            GROUP BY 1,2,3 ORDER BY max(created_at) DESC LIMIT 8""")
if warn:
    group_header('Data-quality warnings (deduplicated)')
    df_show(pd.DataFrame(warn, columns=['Check', 'Severity', 'Subject',
                                        'First seen', 'Last seen', 'Runs']))
st.caption('Free-tier usage: Admin & Status page — target platform cost $0/month.')
