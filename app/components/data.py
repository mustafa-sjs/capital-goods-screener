"""Shared data access for the Streamlit app.

Connection preference: st.secrets['DATABASE_URL'] (Streamlit Cloud ->
Supabase) -> env DATABASE_URL -> local DuckDB file. Reference data is
cached; the app reads precomputed tables and never does heavy calculation
on page load (free-tier survival).
"""
import json, os, sys

import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from src.database.db import connect  # noqa: E402


def _db_url():
    # env first; only touch st.secrets when a secrets file actually exists,
    # otherwise Streamlit renders a red "No secrets files found" box on
    # every page (audited defect #1).
    if os.environ.get('DATABASE_URL'):
        return os.environ['DATABASE_URL']
    for p in (os.path.expanduser('~/.streamlit/secrets.toml'),
              os.path.join(ROOT, '.streamlit', 'secrets.toml')):
        if os.path.exists(p):
            try:
                return st.secrets.get('DATABASE_URL')
            except Exception:
                return None
    return None


@st.cache_resource
def get_db():
    return connect(_db_url())


@st.cache_data(ttl=600)
def payload():
    """Latest full engine payload (everything the original dashboard shows)."""
    db = get_db()
    row = db.fetchall(
        'SELECT payload FROM app_payload ORDER BY snapshot_date DESC LIMIT 1')
    if row:
        return json.loads(row[0][0])
    # local fallback: file
    p = os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')
    return json.load(open(p))


@st.cache_data(ttl=600)
def latest_snapshot():
    db = get_db()
    r = db.fetchall('SELECT max(snapshot_date) FROM feat_screener')
    return r[0][0] if r and r[0][0] else None


@st.cache_data(ttl=600)
def last_run():
    db = get_db()
    r = db.fetchall("""SELECT run_id, mode, finished_at, status, notes
                       FROM refresh_runs ORDER BY started_at DESC LIMIT 1""")
    return r[0] if r else None


def q(sql, params=None):
    return get_db().fetchall(sql, params)


def ph():
    return get_db().ph


def fmt_pct(v, dp=1):
    return '–' if v is None else f'{v:+.{dp}f}%'


def color_move(v):
    if v is None:
        return ''
    return 'color: #0a7d38' if v > 0 else ('color: #c0392b' if v < 0 else '')


BASIS_BANNER = ('Basis: **LTM reported fallback** (FactIQ exposes no consensus '
                'feed — no NTM/LTM mixing anywhere). Mechanical analytics, '
                'not investment advice.')
