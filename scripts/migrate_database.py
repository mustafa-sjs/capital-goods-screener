#!/usr/bin/env python3
"""One-time (re-runnable) migration: local DuckDB -> Supabase Postgres.

    python scripts/migrate_database.py --db-url 'postgresql://...'

Creates the schema on Postgres, upserts every table from the local DuckDB,
then prints source/target row counts side by side. Idempotent — safe to
re-run; it never truncates the target.
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import DB, connect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from restore_backup import KEYS

EXTRA_KEYS = {
    'raw_fundamentals': ['key', 'kind'],
    'feat_close_rows': ['snapshot_date', 'key', 'coverage_group'],
    'feat_close_groups': ['snapshot_date', 'group_display'],
    'feat_scenarios': ['snapshot_date', 'key', 'scenario'],
    'app_payload': ['snapshot_date'],
    'refresh_run_items': ['run_id', 'item'],
    'free_tier_usage': ['as_of', 'metric'],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db-url', required=True)
    args = ap.parse_args()
    src = DB()                      # local duckdb
    dst = connect(args.db_url)     # postgres, schema created
    keys = {**KEYS, **EXTRA_KEYS}
    print(f'{"table":26s} {"local":>8} {"supabase":>9}')
    for t, kc in keys.items():
        rows = src.fetchall(f'SELECT * FROM {t}')
        cols = [r[1] for r in src.fetchall(f"PRAGMA table_info('{t}')")]
        if rows:
            dst.upsert(t, cols, [tuple(r) for r in rows], kc)
        n_dst = dst.fetchall(f'SELECT count(*) FROM {t}')[0][0]
        flag = '' if n_dst >= len(rows) else '  <-- MISMATCH'
        print(f'{t:26s} {len(rows):>8} {n_dst:>9}{flag}')
    src.close(); dst.close()
    print('\nDone. Set the same URL as the DATABASE_URL secret in GitHub and '
          'Streamlit, and production reads/writes go to Supabase.')


if __name__ == '__main__':
    main()
