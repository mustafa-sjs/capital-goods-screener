#!/usr/bin/env python3
"""Restore tables from a Parquet backup directory.

    python scripts/restore_backup.py --dir backups/2026-07-12 [--db-url ...]

Upserts every row from each table file — safe onto an existing database
(never truncates first). See docs/disaster_recovery.md for the full runbook.
"""
import argparse, glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import connect

# natural keys per table (must match schema.sql primary keys)
KEYS = {
    'securities': ['key'], 'coverage_groups': ['group_id'],
    'coverage_members': ['group_id', 'key', 'role'],
    'raw_daily_prices': ['key', 'price_date', 'source'],
    'raw_monthly_prices': ['key', 'price_date', 'source'],
    'raw_fx_rates': ['pair', 'rate_date', 'source'], 'raw_quotes': ['key'],
    'eu_close_snapshots': ['key', 'obs_date', 'benchmark_time'],
    'feat_screener': ['snapshot_date', 'key'],
    'feat_valuation_history': ['key', 'year'],
    'daily_change_events': ['snapshot_date', 'key', 'event_type'],
    'watchlists': ['watchlist_id'], 'watchlist_members': ['watchlist_id', 'key'],
    'saved_screens': ['screen_id'], 'refresh_runs': ['run_id'],
    'validation_results': ['run_id', 'check_name', 'subject'],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--db-url', default=None)
    args = ap.parse_args()
    db = connect(args.db_url)
    import pandas as pd
    for path in sorted(glob.glob(os.path.join(args.dir, '*.parquet'))):
        t = os.path.basename(path)[:-8]
        if t not in KEYS:
            print(f'  skip {t} (no key map)'); continue
        df = pd.read_parquet(path)
        df = df.astype(object).where(pd.notnull(df), None)
        n = db.upsert(t, list(df.columns),
                      [tuple(r) for r in df.itertuples(index=False)], KEYS[t])
        print(f'  {t:24s} {n:>7} rows restored')
    db.close()


if __name__ == '__main__':
    main()
