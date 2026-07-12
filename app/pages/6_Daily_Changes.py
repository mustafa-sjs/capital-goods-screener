import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
from components.data import q, ph

st.set_page_config(page_title='Daily Changes', page_icon='🏭', layout='wide')
st.title('Daily changes')
st.caption('What changed since the previous successful refresh. Snapshots '
           'persist per date, so screen history is auditable.')

dates = [r[0] for r in q('SELECT DISTINCT snapshot_date FROM feat_screener '
                         'ORDER BY 1 DESC')]
if len(dates) < 1:
    st.info('No snapshots yet.'); st.stop()
snap = st.selectbox('Snapshot', dates)

ev = q(f'SELECT key, event_type, detail FROM daily_change_events '
       f'WHERE snapshot_date = {ph()} ORDER BY event_type, key', [snap])
st.subheader(f'Change events — {snap}')
if ev:
    st.dataframe(pd.DataFrame(ev, columns=['Key', 'Event', 'Detail']),
                 hide_index=True, use_container_width=True)
else:
    st.info('No detected changes vs the prior snapshot (classification moves, '
            '±5pp peer-discount shifts, ±5% price moves, universe entries). '
            'Events accumulate as daily snapshots build up.')

st.subheader('Classification snapshot history (auditable screens)')
hist = q("""SELECT snapshot_date, classification, count(*)
            FROM feat_screener GROUP BY 1, 2 ORDER BY 1 DESC, 2""")
st.dataframe(pd.DataFrame(hist, columns=['Snapshot', 'Classification', 'Names']),
             hide_index=True, use_container_width=True)

st.subheader('New validation findings')
v = q("""SELECT run_id, check_name, severity, subject, message
         FROM validation_results ORDER BY created_at DESC LIMIT 20""")
st.dataframe(pd.DataFrame(v, columns=['Run', 'Check', 'Severity', 'Subject', 'Message']),
             hide_index=True, use_container_width=True)
