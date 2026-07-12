import os
import pandas as pd
import streamlit as st
from components.data import get_db, q, ph, payload
from components.ui import df_show, group_header

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
st.title('Admin & system status')

db = get_db()
D = payload()

group_header('Refresh history')
runs = q("""SELECT run_id, mode, started_at, finished_at, status, rows_inserted,
            items_failed, notes FROM refresh_runs ORDER BY started_at DESC LIMIT 15""")
st.dataframe(pd.DataFrame(runs, columns=['Run', 'Mode', 'Started', 'Finished',
             'Status', 'Rows', 'Failed', 'Notes']), hide_index=True,
             use_container_width=True)
fails = q("""SELECT run_id, item, message FROM refresh_run_items
             WHERE status = 'failed' ORDER BY run_id DESC LIMIT 10""")
if fails:
    st.error('Recent failed items:')
    st.dataframe(pd.DataFrame(fails, columns=['Run', 'Item', 'Message']),
                 hide_index=True, use_container_width=True)

group_header('Database')
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
st.dataframe(pd.DataFrame(sorted(counts.items()), columns=['Table', 'Rows']),
             hide_index=True)

group_header('Free-Tier Usage')
SUPABASE_LIMIT_MB = 500     # verify against current supabase.com/pricing
ACTIONS_LIMIT_MIN = 2000    # GitHub Free private-repo minutes/month — verify
rows = []
if size_mb is not None and db.kind == 'postgres':
    pct = size_mb / SUPABASE_LIMIT_MB * 100
    rows.append(('Supabase database', f'{size_mb:.0f} / {SUPABASE_LIMIT_MB} MB',
                 '🟢' if pct < 60 else ('🟡' if pct < 90 else '🔴')))
elif size_mb is not None:
    rows.append(('Local DuckDB (no cloud quota)', f'{size_mb:.0f} MB', '🟢'))
est_daily_min = 3   # measured: price refresh + engine ≈ 2-3 min
est_month = est_daily_min * 23
pct = est_month / ACTIONS_LIMIT_MIN * 100
rows.append(('GitHub Actions (est.)', f'~{est_month} / {ACTIONS_LIMIT_MIN} min/mo',
             '🟢' if pct < 70 else ('🟡' if pct < 95 else '🔴')))
rows.append(('Streamlit Community Cloud', 'free tier — app may sleep when idle', '🟢'))
rows.append(('Paid services enabled', '0', '🟢'))
rows.append(('Estimated monthly platform cost',
             '$0 (excl. FactIQ / LLM tokens)', '🟢'))
st.dataframe(pd.DataFrame(rows, columns=['Resource', 'Usage', 'Status']),
             hide_index=True, use_container_width=True)
st.caption('Thresholds: Actions warn at 70/85/95%, Supabase at 60/75/90%. '
           'Limits are config — verify current provider terms; at the top '
           'band, non-essential scheduled tasks stop (core price refresh last).')

group_header('Controls')
c1, c2 = st.columns(2)
if c1.button('Run validation now'):
    from src.validation.checks import run_checks
    import uuid
    counts = run_checks(db, 'manual-' + uuid.uuid4().hex[:8])
    st.write(counts)
if db.kind == 'duckdb' and c2.button('Refresh prices now (local only)'):
    with st.spinner('Fetching...'):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'refresh.py'),
                            '--mode', 'prices_only'], capture_output=True, text=True)
    st.code((r.stdout + r.stderr)[-1500:])
if db.kind == 'postgres':
    st.caption('In production, trigger refreshes from the GitHub Actions tab '
               '("Run workflow") rather than inside the app — long jobs must '
               'not block the free dyno.')

group_header('Versions')
st.write({'code': subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                                 capture_output=True, text=True, cwd=ROOT).stdout.strip() or 'n/a',
          'data snapshot': D.get('generated'), 'fx as of': D.get('fx_asof'),
          'estimate basis': 'LTM reported fallback (uniform)'})
