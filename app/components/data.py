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
        ver = f'{r[0][0]}|{q[0][0]}'
    except Exception:
        return 'fallback'
    # US intraday layer: a new benchmark/quote or catalyst refresh must
    # invalidate Market & Peers promptly (tables may not exist mid-migration)
    try:
        b = db.fetchall('SELECT max(updated_at) FROM market_benchmark_snapshots')
        e = db.fetchall('SELECT max(retrieved_at) FROM market_events')
        ver += f'|{b[0][0]}|{e[0][0]}'
    except Exception:
        pass
    return ver


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


def core_freshness():
    """(latest market date, core companies current at that date, core total,
    stale core keys). 'Current' = the company's own market's latest completed
    date matches its currency-group latest (exchanges close at different
    times, so one global date would mark whole regions stale)."""
    from src.utils.universe import universe_service
    svc = universe_service()
    core = set(svc['core'])
    try:
        rows = q('SELECT key, quote_date, currency FROM raw_quotes')
    except Exception:
        return '?', 0, len(core), []
    latest_by_ccy, latest_all = {}, ''
    for k, d, ccy in rows:
        if d:
            latest_by_ccy[ccy] = max(latest_by_ccy.get(ccy, ''), str(d))
            latest_all = max(latest_all, str(d))
    stale = sorted(k for k, d, ccy in rows if k in core and d
                   and str(d) < latest_by_ccy.get(ccy, ''))
    have = {k for k, d, ccy in rows if k in core}
    stale += sorted(core - have)
    return latest_all or '?', len(core) - len(stale), len(core), stale


BASIS_HELP = ('Consensus estimates are unavailable in the data sources, so '
              'every valuation multiple uses the latest reported full-period '
              'financials (never a mix of reported and estimated figures). '
              'Prices are delayed public data, not real-time. Mechanical '
              'analytics, not investment advice.')


def status_strip(show_warnings=True):
    """Compact one-line data status shown on every market-dependent page,
    with the fuller basis explanation behind an ⓘ tooltip."""
    latest, n_ok, n_core, stale = core_freshness()
    ver = data_version()
    upd = ver.split('|')[1][:16].replace('T', ', ') if '|' in ver else '?'
    st.markdown(
        f'<div style="font-size:12.5px;color:#4e5a5b;background:#f2f6f6;'
        f'border-radius:6px;padding:5px 10px;margin-bottom:8px">'
        f'Market data through <b>{latest}</b> · Financials: latest reported '
        f'periods · <b>{n_ok} of {n_core}</b> coverage companies current · '
        f'Updated {upd} '
        f'<span title="{BASIS_HELP}" style="cursor:help;opacity:.65">ⓘ data '
        f'basis</span></div>', unsafe_allow_html=True)
    if show_warnings and stale:
        from src.utils.universe import universe_service
        names = universe_service()['names']
        shown = ', '.join(names.get(k, k) for k in stale[:5])
        more = f' and {len(stale) - 5} more' if len(stale) > 5 else ''
        st.warning(f'Prices for {shown}{more} are behind the latest market '
                   f'date — treat those rows as stale (details under '
                   f'Manage → Data Status).')


def freshness_banner():
    """Legacy alias — old pages called freshness_banner()."""
    status_strip()


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


@st.cache_data(ttl=900)
def price_history(key, _version=None):
    """Canonical daily price history for one security: the validated
    database table first, the committed parquet as a documented fallback.
    Returns (DataFrame[session_date, close_raw, close_split, close_tr],
    source_label)."""
    import pandas as pd
    try:
        rows = q(f'SELECT session_date, close_raw, close_split, close_tr '
                 f'FROM canonical_prices WHERE key = {ph()} '
                 f'ORDER BY session_date', [key])
    except Exception:
        rows = []
    if rows:
        df = pd.DataFrame(rows, columns=['session_date', 'close_raw',
                                         'close_split', 'close_tr'])
        df['session_date'] = df['session_date'].astype(str)
        return df, 'validated database history'
    p = os.path.join(ROOT, 'data', 'history', 'prices_daily.parquet')
    df = pd.read_parquet(p)
    df = df[df.key == key][['session_date', 'close_raw', 'close_split',
                            'close_tr']].sort_values('session_date')
    return df.reset_index(drop=True), 'bundled file (development fallback)'


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


# ---- plain-English translations of internal event / check names -----------
EVENT_LABELS = {
    'momentum_state_change': 'Price trend changed',
    'ema_20_60_cross': 'New trend crossover',
    'valuation_state_change': 'Valuation classification changed',
    'peer_discount_threshold': 'Crossed a peer premium/discount threshold',
    'peer_discount_move': 'Premium/discount to peers moved',
    'own_history_extreme': 'Valuation reached an own-history extreme',
    'fundamental_state_change': 'Fundamental direction changed',
    'rev_growth_pct_sign_change': 'Revenue growth changed sign',
    'margin_chg_pp_sign_change': 'Margin trend changed sign',
    'leverage_threshold': 'Leverage crossed 3.0× net debt / EBITDA',
    'new_52w_high': 'New 52-week high',
    'drawdown_threshold': 'Fell more than 20% below the 52-week high',
    'large_price_move': 'Large price move',
    'data_quality_new': 'New data warning',
    'data_quality_resolved': 'Data warning resolved',
    'universe_entry': 'Joined the coverage universe',
    'universe_exit': 'Left the coverage universe',
    'classification_change': 'Classification changed',
    'new_security': 'New company added',
}

CHECK_LABELS = {
    'cross_source_price_conflict': 'Two data sources disagree on a stored price',
    'extreme_daily_move': 'Unusually large one-day price move — possible '
                          'corporate action (split or adjustment) to verify',
    'price_scale_change': 'Stored price changed scale — possible unadjusted '
                          'split or unit error',
    'stale_quote': 'Price has not updated recently',
    'currency_mismatch': 'Quoted currency does not match the reference data',
    'missing_fx_pair': 'No exchange-rate series stored for a quote currency',
    'mixed_estimate_basis': 'Valuation metrics mixed two different bases',
    'unmapped_member': 'A peer-basket member is missing from the security list',
    'flat_price': 'Price unchanged for many sessions — possible dead listing',
    'candidate_missing': 'The newly computed dataset could not be read',
    'universe_coverage_drop': 'The new dataset covers far fewer companies '
                              'than the current one',
    'snapshot_regression': 'The new dataset is older than the published one',
    'feature_after_price': 'Calculated metrics are dated after the newest '
                           'stored price',
    'canonical_stale': 'The stored price history has not updated recently',
    'missing_canonical_history': 'No stored price history for a company',
    'multi_currency': 'One company has prices stored in multiple currencies',
    'invalid_price': 'A stored price is zero or negative',
    'price_scale_implausible': 'A price sits far outside its 52-week range — '
                               'possible unit or scale error',
    'stale_vs_market': 'Price is behind the latest date for its market',
    'core_coverage_stale': 'Several coverage companies have stale prices',
    'missing_symbol_mapping': 'A US peer has no Finnhub symbol configured',
    'duplicate_finnhub_symbol': 'Two securities map to the same Finnhub symbol',
    'unexpected_exchange': 'A Finnhub mapping exists for a non-US listing',
    'cross_source_timestamp_gap': 'Finnhub and Yahoo prices differ but were '
                                  'observed at different times — market '
                                  'movement, not a provider conflict',
}


def event_label(etype):
    return EVENT_LABELS.get(etype, etype.replace('_', ' ').capitalize())


def check_label(name):
    return CHECK_LABELS.get(name, name.replace('_', ' ').capitalize())
