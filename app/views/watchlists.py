import os
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from components.data import get_db, payload, q, ph
from components.ui import style_table, df_show, group_header

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
        'Remove': False,
        'Key': k, 'Company': D['names'].get(k, k), 'Note': note, 'Priority': prio,
        'Thesis': ts, 'Added': str(added)[:10],
        'EV/EBITDA': scr.get(k, {}).get('ev_ebitda_ltm'),
        'vs peers %': scr.get(k, {}).get('prem_disc_vs_peers_pct'),
        'rel 3M pp': scr.get(k, {}).get('rel_3m_pct')}
        for k, note, prio, ts, added in rows])
    edited = st.data_editor(df, hide_index=True, use_container_width=True,
                            disabled=[c for c in df.columns if c != 'Remove'],
                            column_config={
        'Remove': st.column_config.CheckboxColumn('Remove'),
        'EV/EBITDA': st.column_config.NumberColumn(format='%.1f x'),
        'vs peers %': st.column_config.NumberColumn(format='%+.1f%%'),
        'rel 3M pp': st.column_config.NumberColumn(format='%+.1f')})
    to_rm = edited[edited['Remove']]['Key'].tolist()
    if to_rm and st.button(f'Remove {len(to_rm)} selected'):
        for k in to_rm:
            db.execute(f'DELETE FROM watchlist_members WHERE watchlist_id = {ph()} '
                       f'AND key = {ph()}', [pick[0], k])
        st.cache_data.clear(); st.rerun()
    st.download_button('Export CSV', df.drop(columns=['Remove']).to_csv(index=False),
                       f'{pick[1]}.csv')
else:
    st.info('Empty list — add securities above. Watchlist data lives in the '
            'database (Supabase in production), so it survives app restarts.')
