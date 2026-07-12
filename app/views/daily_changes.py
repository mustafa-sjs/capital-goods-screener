import os
import pandas as pd
import streamlit as st
from components.data import q, ph
from components.ui import df_show, group_header

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
group_header(f'Change events — {snap}')
if ev:
    df_show(pd.DataFrame(ev, columns=['Key', 'Event', 'Detail']))
else:
    st.info('No detected changes vs the prior snapshot (classification moves, '
            '±5pp peer-discount shifts, ±5% price moves, universe entries). '
            'Events accumulate as daily snapshots build up.')

group_header('Classification snapshot history (auditable screens)')
hist = q("""SELECT snapshot_date, classification, count(*)
            FROM feat_screener GROUP BY 1, 2 ORDER BY 1 DESC, 2""")
df_show(pd.DataFrame(hist, columns=['Snapshot', 'Classification', 'Names']))

group_header('New validation findings')
v = q("""SELECT run_id, check_name, severity, subject, message
         FROM validation_results ORDER BY created_at DESC LIMIT 20""")
df_show(pd.DataFrame(v, columns=['Run', 'Check', 'Severity', 'Subject', 'Message']))
