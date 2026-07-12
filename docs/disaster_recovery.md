# Disaster recovery

Free-tier backups are NOT paid-grade resilience: recovery is manual and
recent watchlist edits since the last backup can be lost. Everything else is
reconstructible because **git holds the raw data files** and the engine is
deterministic.

## Restore the database (Supabase died / was paused / corrupted)
```bash
# from the repo (any machine):
./.venv/bin/python scripts/load_db.py                 # rebuild local DuckDB from files
./.venv/bin/python scripts/migrate_database.py --db-url 'postgresql://NEW_URL'
```
Watchlists/saved screens: restore from the newest parquet backup —
`python scripts/restore_backup.py --dir backups/<date> --db-url '...'`
(weekly GitHub artifact or local `backups/`).

## Redeploy the app
share.streamlit.io → the app → Reboot; or delete + recreate pointing at
`app/Home.py` (2 minutes). Re-enter the `DATABASE_URL` secret.

## Reconnect secrets
GitHub: repo Settings → Secrets → Actions → `DATABASE_URL`.
Streamlit: app Settings → Secrets → `DATABASE_URL = "..."`.
Supabase password lost → Supabase dashboard → Settings → Database → reset.

## Corrupted price update
Nothing is deleted automatically, so bad rows sit in `raw_daily_prices`
with their `source`. Fix:
```bash
# inspect, then remove the bad source rows for the affected window
./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.database.db import connect; db=connect()
db.execute(\"DELETE FROM raw_daily_prices WHERE key='XXX' AND source='yahoo' AND price_date >= '2026-01-01'\")"
python scripts/refresh.py --mode daily      # refetch + rebuild
```
Git history of `data/raw/` gives every prior file state: `git log -- data/raw/daily_XXX.json`.

## Incorrect peer map committed
`git revert <commit>` (or edit the YAML back), then
`python scripts/refresh.py --mode rebuild_features`. Feature snapshots are
per-date, so the bad snapshot stays visible in history — that is intentional
auditability, not damage.

## Revert to a previous code state
```bash
git log --oneline          # find the good commit
git revert <bad>..HEAD     # or: git checkout -b rescue <good>
python -m pytest tests/ -q # confirm
```

## Rerun a full backfill (nuclear option)
Prices: delete `data/raw/daily_*.json` for affected names → a Claude session
re-fetches FactIQ history, or accept Yahoo `range=10y` via a small tweak to
the adapter (documented in `src/ingestion/yahoo_prices.py`). Fundamentals:
Claude session ("full FactIQ refresh"). Then `load_db.py` + `migrate_database.py`.
