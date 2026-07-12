import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from components.data import get_db, payload, q, ph

st.set_page_config(page_title='Watchlists', page_icon='🏭', layout='wide')
st.title('Watchlists')

db = get_db()
D = payload()
KINDS = ['potential_longs', 'potential_shorts', 'holdings',
         'upcoming_earnings', 'research_required', 'custom']

# ensure the standard lists exist
existing = {r[1]: r[0] for r in q('SELECT watchlist_id, name FROM watchlists')}
for kind in KINDS[:-1]:
    name = kind.replace('_', ' ').title()
    if name not in existing:
        db.upsert('watchlists', ['watchlist_id', 'name', 'kind', 'created_at'],
                  [(kind, name, kind, datetime.now(timezone.utc).replace(tzinfo=None))],
                  ['watchlist_id'])
lists = q('SELECT watchlist_id, name, kind FROM watchlists ORDER BY name')
pick = st.selectbox('Watchlist', lists, format_func=lambda r: r[1])

with st.form('add'):
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    key = c1.selectbox('Security', sorted(D['names']),
                       format_func=lambda k: f"{D['names'][k]} ({k})")
    note = c2.text_input('Note / thesis')
    prio = c3.selectbox('Priority', ['high', 'medium', 'low'])
    thesis = c4.selectbox('Thesis status', ['idea', 'researching', 'active', 'closed'])
    if st.form_submit_button('Add / update'):
        db.upsert('watchlist_members',
                  ['watchlist_id', 'key', 'note', 'priority', 'thesis_status', 'added_at'],
                  [(pick[0], key, note, prio, thesis,
                    datetime.now(timezone.utc).replace(tzinfo=None))],
                  ['watchlist_id', 'key'])
        st.cache_data.clear(); st.rerun()

rows = q(f"""SELECT m.key, m.note, m.priority, m.thesis_status, m.added_at
             FROM watchlist_members m WHERE m.watchlist_id = {ph()}""", [pick[0]])
if rows:
    scr = {r['key']: r for r in D['screener']}
    df = pd.DataFrame([{
        'Key': k, 'Company': D['names'].get(k, k), 'Note': note, 'Priority': prio,
        'Thesis': ts, 'Added': str(added)[:10],
        'EV/EBITDA': scr.get(k, {}).get('ev_ebitda_ltm'),
        'vs peers %': scr.get(k, {}).get('prem_disc_vs_peers_pct'),
        'rel 3M pp': scr.get(k, {}).get('rel_3m_pct')}
        for k, note, prio, ts, added in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button('Export CSV', df.to_csv(index=False), f'{pick[1]}.csv')
    rm = st.selectbox('Remove member', ['—'] + [r[0] for r in rows])
    if rm != '—' and st.button('Remove'):
        db.execute(f'DELETE FROM watchlist_members WHERE watchlist_id = {ph()} '
                   f'AND key = {ph()}', [pick[0], rm])
        st.cache_data.clear(); st.rerun()
else:
    st.info('Empty list — add securities above. Watchlist data lives in the '
            'database (Supabase in production), so it survives app restarts.')
