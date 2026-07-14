# Capital Goods Research Platform

A persistent, zero-cost equity-research platform and stock screener for a
Capital Goods coverage pack: 30 coverage names, 114 securities, curated peer
baskets, three valuation layers (direct peers / deduplicated sector / own
history), peer read-across, mechanical scenarios and an auditable screener.

**Core question it answers:** which stocks look mispriced relative to their
direct peers, wider sector and own history — and which dislocations are
supported or contradicted by fundamentals, relative price performance and
identifiable catalysts.

## Where things live

| Component | Location |
|---|---|
| Code, config, docs, raw data | this repository (`/Users/Mustafa/capital-goods-dashboard` locally) |
| Local dev database | `data/capital_goods.duckdb` (DuckDB) + `data/archive/*.parquet` |
| Production database | Supabase Postgres (free tier) via `DATABASE_URL` |
| Remote app | Streamlit Community Cloud (deploys `app/Home.py`) |
| Scheduling | `.github/workflows/` (daily refresh, intraday EU-close, tests, backup) |
| Legacy dashboard | `capital_goods_dashboard.html` (embedded: Manage & Help → Legacy Dashboard) |

## App navigation (v2.7)

**Research:** Overview (what moved / what changed / is the data current) ·
Stock Screener (tabs: Overview, Valuation, Fundamentals, Price Trend, Risk —
Price Trend is the consolidated momentum screener) · Compare Companies
(2–5 names side by side) · Company Analysis (tabs: Summary, Valuation,
Financials, Price Trend, Scenarios) · Market & Peers (peer read-across).
**Manage & Help:** Watchlists · Data Status (plain-English warnings, change
history, admin internals) · Methodology (metric dictionary + definitions) ·
Legacy Dashboard. Shared services: `src/utils/universe.py`
(universe/subgroups, hard-validated: exactly 30 core companies) and
`src/utils/metrics.py` (every user-facing label and definition) — no page
defines its own membership lists or metric labels.

## How it refreshes

- **Daily (automated):** `refresh.py --mode daily` — incremental Yahoo quotes
  + ~1 month of daily bars per name (never full history), FX, engine
  recompute, validation gate, publish to DB, static HTML rebuild. Idempotent:
  upserts on `(key, price_date, source)`.
- **Intraday (automated):** true 16:30 UK benchmark snapshots for European
  names from 5-minute bars — real "move since European close".
- **Fundamentals (manual, quarterly-ish):** FactIQ speaks only through an
  interactively-authenticated session — open Claude Code here and say
  *"run the quarterly FactIQ refresh"*. `--mode fundamentals` reports staleness.

## Run locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scripts/load_db.py          # build local DB from files
./.venv/bin/python scripts/refresh.py --mode daily
./.venv/bin/streamlit run app/Home.py          # local app
open capital_goods_dashboard.html              # original rich dashboard
```

## Edit peers / add a company / add a sector

`config/coverage_packs/capital_goods.yaml` is the single source of truth
(securities + subgroups + peer baskets + Yahoo symbols). Edit it, then
`python scripts/refresh.py --mode rebuild_features`. A new company also needs
its FactIQ statements fetched once (Claude session) into `data/raw/`. A new
sector = a new coverage-pack YAML — no core rewrites. The engine keeps
equivalent fallback literals; `tests/unit/test_db_and_config.py` fails if
they drift.

## Recover from a failed refresh

1. App → Data Status → Administration → read the run's notes / failed items.
2. Re-run: `python scripts/refresh.py --mode daily` (safe to repeat).
3. Single names: `python scripts/refresh_prices.py KEY`.
4. Source down? Latest stored data keeps serving (marked stale);
   `python scripts/import_prices.py --file prices.csv` as manual fallback.
5. Full restore: `docs/disaster_recovery.md`.

## Cost

$0/month by design (GitHub Free private repo + Actions, Streamlit Community
Cloud, Supabase Free, keyless Yahoo endpoint), excluding FactIQ/LLM tokens.
Guards: Data Status free-tier panel, workflow timeouts/concurrency caps,
7-day artifact retention. **No investment recommendations anywhere.**
