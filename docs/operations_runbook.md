# Operations runbook (non-technical)

## Open the app
Bookmark your Streamlit URL (after deployment — see docs/deployment.md).
Locally: `./.venv/bin/streamlit run app/Home.py`. The free app sleeps when
idle; first load takes ~30s — that's normal.

## Is my data current?
Home page, top-left: **"Data as of …"** and **"Last refresh"**. Green = a
successful run today (weekdays). The header date is the truth — it comes
from the newest stored quote, not the calendar.

## Daily routine (2 minutes)
1. Open the app → Home: check refresh status + biggest moves.
2. **Daily Changes** page: classification moves, ±5pp peer-discount shifts,
   screen entries/exits.
3. Investigate anything on the stale-data / validation list.
4. Glance at Admin → Free-Tier Usage (should be all green, $0).

## Run a manual refresh
- Cloud: GitHub repo → Actions → daily-refresh → **Run workflow**.
- Local: `./scripts/refresh.sh` (or Admin page → "Refresh prices now").

## A refresh failed — what now?
Admin page shows the run's notes and per-security failures. One or two
failed names = transient Yahoo hiccups; the next run heals them (backfill is
automatic). Whole-run failure = read the notes; re-running is always safe.
CRITICAL validation findings intentionally block publication — the app keeps
serving the last good snapshot.

## Edit peers / add a company / add a sector
`config/coverage_packs/capital_goods.yaml` → edit → run
`python scripts/refresh.py --mode rebuild_features` (or ask Claude). New
companies need one FactIQ statement fetch (Claude session). New sector =
new YAML pack file.

## Export data
Every table view has a CSV button; root `capital_goods_*.csv` files always
hold the latest full extracts; `python scripts/export_backup.py` dumps
everything to Parquet.

## Restore / disaster recovery
`docs/disaster_recovery.md`. Short version: the git repo + any parquet
backup reconstructs everything; `scripts/restore_backup.py` reloads a DB.

## Who controls what
| Component | Service | Where |
|---|---|---|
| Code, data files, schedules | GitHub (your account) | github.com → capital-goods-screener |
| Production DB | Supabase (your account) | supabase.com dashboard |
| App hosting | Streamlit (your account) | share.streamlit.io |
| Fundamentals source | FactIQ (via Claude Code) | this project folder |
| Local fallback refresh | launchd on this Mac | `launchctl list | grep capitalgoods` |

## Verify it still costs $0
Admin → Free-Tier Usage panel: paid services must read **0**. Independently:
GitHub → Settings → Billing (Actions minutes), Supabase dashboard → usage,
and confirm no payment method is on file anywhere.
