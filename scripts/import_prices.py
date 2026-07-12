#!/usr/bin/env python3
"""Manual CSV price import — the last-resort adapter.

    python scripts/import_prices.py --file prices.csv

CSV header: key,price_date,close[,open,high,low,volume,currency]
Upserts on (key, price_date, 'manual_csv'); running twice is safe.
"""
import argparse, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.database.db import connect
from src.ingestion.manual_csv import ManualCSVAdapter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--db-url', default=None)
    args = ap.parse_args()
    db = connect(args.db_url)
    known = {r[0] for r in db.fetchall('SELECT key FROM securities')}
    ad = ManualCSVAdapter(args.file)
    rows, skipped = [], 0
    ts = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in ad.rows():
        if r['key'] not in known or r['close'] is None:
            skipped += 1
            continue
        rows.append((r['key'], r['date'], r['open'], r['high'], r['low'],
                     r['close'], int(r['volume']) if r['volume'] else None,
                     r['currency'], 'manual_csv', ts, 'ok'))
    n = db.upsert('raw_daily_prices',
                  ['key', 'price_date', 'open', 'high', 'low', 'close', 'volume',
                   'currency', 'source', 'ingested_at', 'quality'],
                  rows, ['key', 'price_date', 'source'])
    print(f'imported {n} rows, skipped {skipped} (unknown key / missing close)')
    db.close()


if __name__ == '__main__':
    main()
