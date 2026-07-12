import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamlit as st

st.set_page_config(page_title='Capital Goods — Research Platform',
                   page_icon='🏭', layout='wide')

nav = st.navigation({
    'Research': [
        st.Page('views/home.py', title='Home', icon='🏠', default=True),
        st.Page('views/full_dashboard.py', title='Full Dashboard', icon='📊'),
        st.Page('views/market_close.py', title='Market Close & Read-Across', icon='🌍'),
        st.Page('views/rerating.py', title='Sector Rerating', icon='📈'),
        st.Page('views/screener.py', title='Screener', icon='🔎'),
        st.Page('views/drilldown.py', title='Company Drill-Down', icon='🏢'),
        st.Page('views/scenarios.py', title='Scenarios', icon='⚖️'),
        st.Page('views/daily_changes.py', title='Daily Changes', icon='🔔'),
    ],
    'Manage': [
        st.Page('views/watchlists.py', title='Watchlists', icon='⭐'),
        st.Page('views/admin.py', title='Admin & Status', icon='🛠️'),
    ],
})
nav.run()
