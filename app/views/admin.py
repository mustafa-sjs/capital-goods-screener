"""Data Status — is the data current, and what needs review?

Plain-English data warnings and the full change history sit up front;
pipeline internals (run IDs, database tables, raw check output) remain
available under Administration for advanced users.
"""
import json, os, subprocess, sys, uuid

import pandas as pd
import streamlit as st

from components.data import (get_db, q, ph, payload, data_version,
                             status_strip, check_label, event_label,
                             core_freshness)
from components.ui import df_show, section, page_header, style_table

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
page_header('Data Status',
            'Whether prices and financials are current, what the checks '
            'found, and what changed — in plain English.')
status_strip()

db = get_db()
D = payload(data_version())

# ------------------------------------------------ freshness by company -----
latest, n_ok, n_core, stale = core_freshness()
section('Coverage freshness')
c1, c2, c3 = st.columns(3)
c1.metric('Latest completed market date', latest)
c2.metric('Coverage companies current', f'{n_ok} of {n_core}')
c3.metric('Companies needing attention', len(stale))
if stale:
    from src.utils.universe import universe_service
    names = universe_service()['names']
    st.warning('Prices behind their market\'s latest date: '
               + ', '.join(names.get(k, k) for k in stale))

# ------------------------------------------------ findings, translated -----
section('Data warnings in plain English',
        'Each finding is translated from the internal check that produced '
        'it. Raw technical details are under Administration below.')
warn = q("""SELECT check_name, severity, subject, max(message),
            min(created_at), max(created_at), count(*)
            FROM validation_results
            WHERE severity IN ('warning','error','critical')
            GROUP BY 1,2,3 ORDER BY max(created_at) DESC LIMIT 25""")
if warn:
    names = D.get('names', {})
    rows = []
    for check, sev, subject, msg, first, last, n in warn:
        comp = subject.split(':')[0] if subject else ''
        rows.append({
            'What needs review': check_label(check),
            'Company / item': names.get(comp, subject),
            'Severity': {'warning': 'Review', 'error': 'Important',
                         'critical': 'Blocking'}.get(sev, sev),
            'First seen': str(first)[:10], 'Last seen': str(last)[:10]})
    df_show(pd.DataFrame(rows))
    st.caption('“Blocking” findings stop new data from being published '
               'until resolved. Detail (including the raw check message) is '
               'under Administration → raw findings.')
else:
    st.success('No open data warnings.')

# ------------------------------------------------ recent changes (tape) ----
section('Recent changes — full history',
        'Deterministic day-on-day changes across valuation, fundamentals, '
        'price and trend. Repeats are consolidated, never re-spammed.')
rows = q("""SELECT key, event_type, detail,
                   min(snapshot_date), max(snapshot_date), count(*)
            FROM daily_change_events
            GROUP BY key, event_type, detail
            ORDER BY max(snapshot_date) DESC, key LIMIT 400""")
if rows:
    scr = {r['key']: r for r in D['screener']}
    recs = []
    for k, etype, detail, first, last, n in rows:
        try:
            dd = json.loads(detail)
        except Exception:
            dd = {'note': detail}
        recs.append({
            'Company': D['names'].get(k, k),
            'What changed': event_label(etype),
            'Previous': '' if dd.get('prev') is None else str(dd.get('prev')),
            'Current': '' if dd.get('cur') is None else str(dd.get('cur')),
            'Detail': dd.get('note', ''),
            'First seen': str(first), 'Last seen': str(last), 'Days': n,
            'Subgroup': scr.get(k, {}).get('subgroup', '')})
    df = pd.DataFrame(recs)
    fc1, fc2 = st.columns(2)
    cat = fc1.multiselect('Type', sorted(df['What changed'].unique()))
    sub = fc2.multiselect('Subgroup',
                          sorted(x for x in df['Subgroup'].unique() if x))
    f = df.copy()
    if cat:
        f = f[f['What changed'].isin(cat)]
    if sub:
        f = f[f['Subgroup'].isin(sub)]
    df_show(f.drop(columns=['Subgroup']), height=420)
    st.download_button('Download change history (CSV)', f.to_csv(index=False),
                       'recent_changes.csv')
else:
    st.info('No changes recorded yet — the history fills as daily updates '
            'accumulate.')

# ------------------------------------------------ administration -----------
with st.expander('Administration (pipeline internals, database, controls)'):
    section('Refresh history')
    runs = q("""SELECT run_id, mode, started_at, finished_at, status,
                rows_inserted, items_failed, notes FROM refresh_runs
                ORDER BY started_at DESC LIMIT 15""")
    st.dataframe(pd.DataFrame(runs, columns=['Run', 'Mode', 'Started',
                 'Finished', 'Status', 'Rows', 'Failed', 'Notes']),
                 hide_index=True, use_container_width=True)
    fails = q("""SELECT item, count(*), max(run_id), max(message)
                 FROM refresh_run_items WHERE status = 'failed'
                 GROUP BY item ORDER BY 2 DESC LIMIT 10""")
    if fails:
        st.error('Recently failed items:')
        st.dataframe(pd.DataFrame(fails, columns=['Item', 'Times', 'Last run',
                     'Message']), hide_index=True, use_container_width=True)

    section('Raw findings (untranslated)')
    raw = q("""SELECT run_id, check_name, severity, subject, message,
               created_at FROM validation_results
               ORDER BY created_at DESC LIMIT 50""")
    st.dataframe(pd.DataFrame(raw, columns=['Run', 'Check', 'Severity',
                 'Subject', 'Message', 'At']), hide_index=True,
                 use_container_width=True)

    section('Database')
    counts = db.table_counts()
    tot_rows = sum(counts.values())
    c1, c2, c3 = st.columns(3)
    c1.metric('Environment', 'Supabase Postgres' if db.kind == 'postgres'
              else 'Local DuckDB')
    c2.metric('Total rows', f'{tot_rows:,}')
    size_mb = None
    if db.kind == 'duckdb':
        p = os.path.join(ROOT, 'data', 'capital_goods.duckdb')
        size_mb = os.path.getsize(p) / 1e6 if os.path.exists(p) else 0
    else:
        try:
            size_mb = q("SELECT pg_database_size(current_database())")[0][0] / 1e6
        except Exception:
            pass
    c3.metric('DB size', f'{size_mb:.0f} MB' if size_mb else '?')
    st.dataframe(pd.DataFrame(sorted(counts.items()),
                 columns=['Table', 'Rows']), hide_index=True)

    section('Free-tier usage')
    SUPABASE_LIMIT_MB = 500     # verify against current supabase.com/pricing
    ACTIONS_LIMIT_MIN = 2000    # GitHub Free private-repo minutes/month
    rows = []
    if size_mb is not None and db.kind == 'postgres':
        pct = size_mb / SUPABASE_LIMIT_MB * 100
        rows.append(('Supabase database',
                     f'{size_mb:.0f} / {SUPABASE_LIMIT_MB} MB',
                     '🟢' if pct < 60 else ('🟡' if pct < 90 else '🔴')))
    elif size_mb is not None:
        rows.append(('Local DuckDB (no cloud quota)', f'{size_mb:.0f} MB', '🟢'))
    est_month = 3 * 23
    pct = est_month / ACTIONS_LIMIT_MIN * 100
    rows.append(('GitHub Actions (est.)',
                 f'~{est_month} / {ACTIONS_LIMIT_MIN} min/mo',
                 '🟢' if pct < 70 else ('🟡' if pct < 95 else '🔴')))
    rows.append(('Streamlit Community Cloud',
                 'free tier — app may sleep when idle', '🟢'))
    rows.append(('Estimated monthly platform cost',
                 '$0 (excl. FactIQ / LLM tokens)', '🟢'))
    st.dataframe(pd.DataFrame(rows, columns=['Resource', 'Usage', 'Status']),
                 hide_index=True, use_container_width=True)

    section('Controls')
    c1, c2 = st.columns(2)
    if c1.button('Run validation now'):
        from src.validation.checks import run_checks
        counts = run_checks(db, 'manual-' + uuid.uuid4().hex[:8])
        st.write(counts)
    if db.kind == 'duckdb' and c2.button('Refresh prices now (local only)'):
        with st.spinner('Fetching...'):
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, 'scripts', 'refresh.py'),
                                '--mode', 'prices_only'],
                               capture_output=True, text=True)
        st.code((r.stdout + r.stderr)[-1500:])
    if db.kind == 'postgres':
        st.caption('In production, trigger refreshes from the GitHub Actions '
                   'tab ("Run workflow") rather than inside the app.')

    section('Versions')
    run = None
    st.write({'code': subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                                     capture_output=True, text=True,
                                     cwd=ROOT).stdout.strip() or 'n/a',
              'data snapshot': D.get('generated'), 'fx as of': D.get('fx_asof'),
              'financials basis': 'latest reported periods'})
