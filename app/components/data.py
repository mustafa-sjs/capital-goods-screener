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


def data_version():
    """Cheap version stamp: changes the cache key the moment a new snapshot
    or fresher quotes are published — no more fixed-TTL stale serving."""
    try:
        db = get_db()
        r = db.fetchall('SELECT max(snapshot_date) FROM app_payload')
        q = db.fetchall('SELECT max(refreshed_at) FROM raw_quotes')
        return f'{r[0][0]}|{q[0][0]}'
    except Exception:
        return 'fallback'


def freshness():
    """(latest quote date, quotes at that date, total, oldest core lag) for
    the visible status line on market-data pages."""
    try:
        db = get_db()
        rows = db.fetchall('SELECT quote_date, count(*) FROM raw_quotes '
                           'GROUP BY quote_date ORDER BY quote_date DESC')
        latest = str(rows[0][0]) if rows else '?'
        at_latest = rows[0][1] if rows else 0
        total = sum(r[1] for r in rows)
        return latest, at_latest, total
    except Exception:
        return '?', 0, 0


def freshness_banner():
    latest, n, total = freshness()
    ver = data_version()
    st.caption(f'Prices updated: {ver.split("|")[1][:16]} · latest market '
               f'observation: {latest} · coverage at latest date: {n}/{total}. '
               f'Quotes are delayed public data, not real-time.')
    if total and n < total * 0.8:
        st.warning(f'{total - n} securities are behind the latest market date — '
                   'treat their rows as stale (see Admin for detail).')


@st.cache_data(ttl=300)
def payload(_version=None):
    """Latest full engine payload; cache keyed by data_version()."""
    db = get_db()
    row = db.fetchall(
        'SELECT payload FROM app_payload ORDER BY snapshot_date DESC LIMIT 1')
    if row:
        return json.loads(row[0][0])
    # local fallback: file
    p = os.path.join(ROOT, 'data', 'computed', 'dashboard_data.json')
    return json.load(open(p))


@st.cache_data(ttl=300)
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
