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
    c1, c2, c3 = st.columns([2, 1, 1])
    key = c1.selectbox('Security', sorted(D['names']),
                       format_func=lambda k: f"{D['names'][k]} ({k})")
    prio = c2.selectbox('Priority', ['high', 'medium', 'low'])
    thesis_st = c3.selectbox('Thesis status', ['idea', 'researching', 'active', 'closed'])
    note = st.text_input('One-line note')
    with st.expander('Thesis detail (optional — monitored deterministically)'):
        thesis = st.text_area('Thesis summary', height=68)
        b1, b2, b3 = st.columns(3)
        bull = b1.text_area('Bull case', height=68)
        base = b2.text_area('Base case', height=68)
        bear = b3.text_area('Bear case', height=68)
        cat1, cat2 = st.columns(2)
        catalyst = cat1.text_input('Expected catalyst')
        cat_date = cat2.date_input('Catalyst date', value=None)
        invalid = st.text_input('Invalidation condition (what would kill the thesis)')
        review = st.date_input('Next review date', value=None)
    if st.form_submit_button('Add / update'):
        # thesis-change log: never overwrite history silently
        old = q(f'SELECT thesis FROM watchlist_members WHERE watchlist_id = {ph()} '
                f'AND key = {ph()}', [pick[0], key])
        if old and old[0][0] and old[0][0] != thesis:
            db.execute(f'INSERT INTO saved_screens (screen_id, name, definition, created_at) '
                       f'VALUES ({ph()}, {ph()}, {ph()}, {ph()})',
                       [f'thesislog-{key}-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}',
                        f'THESIS LOG {key}', old[0][0],
                        datetime.now(timezone.utc).replace(tzinfo=None)])
        db.upsert('watchlist_members',
                  ['watchlist_id', 'key', 'note', 'priority', 'thesis_status',
                   'added_at', 'thesis', 'bull_case', 'base_case', 'bear_case',
                   'catalyst', 'catalyst_date', 'invalidation', 'review_date'],
                  [(pick[0], key, note, prio, thesis_st,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    thesis, bull, base, bear, catalyst,
                    str(cat_date) if cat_date else None, invalid,
                    str(review) if review else None)],
                  ['watchlist_id', 'key'])
        st.cache_data.clear(); st.rerun()

# deterministic monitoring triggers across ALL watchlists
trig = []
allm = q('SELECT watchlist_id, key, catalyst, catalyst_date, review_date, '
         'invalidation FROM watchlist_members')
scr2 = {r['key']: r for r in D['screener']}
from datetime import date as _date
for wl, k, cat, cd, rd, inv in allm:
    s2 = scr2.get(k, {})
    if cd and 0 <= (_date.fromisoformat(str(cd)[:10]) - _date.today()).days <= 14:
        trig.append((k, 'catalyst approaching', f'{cat or "catalyst"} on {cd}'))
    if rd and _date.fromisoformat(str(rd)[:10]) <= _date.today():
        trig.append((k, 'review due', f'review date {rd} reached'))
    if s2.get('momentum_state') in ('emerging breakdown', 'established downtrend'):
        trig.append((k, 'momentum condition', f"state: {s2['momentum_state']} — requires review"))
    if (s2.get('nd_ebitda') or 0) > 3:
        trig.append((k, 'leverage condition', f"ND/EBITDA {s2['nd_ebitda']}x > 3.0x"))
if trig:
    st.warning('**Conditions triggered (requires review — not advice):**')
    st.dataframe(pd.DataFrame(trig, columns=['Key', 'Trigger', 'Detail']),
                 hide_index=True, use_container_width=True)

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
