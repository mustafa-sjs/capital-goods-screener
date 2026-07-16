#!/usr/bin/env python3
"""Export critical tables to compressed Parquet (zero-cost backup layer).

    python scripts/export_backup.py [--out backups/2026-07-12] [--db-url ...]

Exports everything needed to reconstruct the platform state that is NOT
already in git (git holds code, config and raw data files): feature
snapshots, watchlists, screens, refresh history, EU-close snapshots.
"""
import argparse, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import connect

TABLES = ['securities', 'coverage_groups', 'coverage_members', 'raw_daily_prices',
          'raw_monthly_prices', 'raw_fx_rates', 'raw_quotes', 'eu_close_snapshots',
          'market_benchmark_snapshots', 'market_events',
          'feat_screener', 'feat_valuation_history', 'daily_change_events',
          'watchlists', 'watchlist_members', 'saved_screens', 'refresh_runs',
          'validation_results']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(
        ROOT, 'backups', datetime.now(timezone.utc).strftime('%Y-%m-%d')))
    ap.add_argument('--db-url', default=None)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    db = connect(args.db_url)
    import pandas as pd
    for t in TABLES:
        rows = db.fetchall(f'SELECT * FROM {t}')
        cols = [r[0] for r in db.fetchall(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{t}' ORDER BY ordinal_position")]
        pd.DataFrame(rows, columns=cols[:len(rows[0])] if rows else cols) \
          .to_parquet(os.path.join(args.out, f'{t}.parquet'), compression='zstd')
        print(f'  {t:24s} {len(rows):>7} rows')
    print(f'backup written to {args.out}')
    db.close()


if __name__ == '__main__':
    main()
