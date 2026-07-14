import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamlit as st

st.set_page_config(page_title='Capital Goods — Research Platform',
                   page_icon='🏭', layout='wide')

# Research = the analyst workflow (find -> compare -> understand -> trust).
# Manage & Help = housekeeping, definitions and the retained legacy view.
# The former Momentum, Sector Rerating, Scenarios, Drill-Down and Signal
# Change Tape pages were consolidated, not removed: momentum lives in
# Stock Screener -> Price Trend; rerating charts and scenarios live in
# Company Analysis; the change tape lives in Overview + Data Status.
nav = st.navigation({
    'Research': [
        st.Page('views/home.py', title='Overview', icon='🏠', default=True),
        st.Page('views/screener.py', title='Stock Screener', icon='🔎'),
        st.Page('views/compare.py', title='Compare Companies', icon='⚖️'),
        st.Page('views/company.py', title='Company Analysis', icon='🏢'),
        st.Page('views/market_close.py', title='Market & Peers', icon='🌍'),
    ],
    'Manage & Help': [
        st.Page('views/watchlists.py', title='Watchlists', icon='⭐'),
        st.Page('views/admin.py', title='Data Status', icon='🛠️'),
        st.Page('views/methodology.py', title='Methodology', icon='📖'),
        st.Page('views/full_dashboard.py', title='Legacy Dashboard', icon='🗂️'),
    ],
})
nav.run()
