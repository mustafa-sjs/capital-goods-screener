import json, os
import streamlit as st
import streamlit.components.v1 as components
from components.data import payload, data_version

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
st.title('Full dashboard (original rich view)')
st.caption('The validated single-file dashboard, embedded unchanged and rebuilt '
           'from the latest database snapshot — pixel-identical to the original '
           'six-page product.')

tpl_path = os.path.join(ROOT, 'scripts', 'dashboard_template.html')
html_path = os.path.join(ROOT, 'capital_goods_dashboard.html')
if os.path.exists(tpl_path):
    html = open(tpl_path).read().replace(
        '__FACTIQ_DATA__', json.dumps({'dash': payload(data_version())}))
elif os.path.exists(html_path):
    html = open(html_path).read()
else:
    st.error('Dashboard template not found in this deployment.')
    st.stop()
components.html(html, height=1600, scrolling=True)
st.caption('Tip: the standalone file capital_goods_dashboard.html opens offline too; deep-link pages with ?page=p2 … ?page=p6.')
