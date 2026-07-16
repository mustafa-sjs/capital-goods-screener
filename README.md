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
- **US intraday (automated, v2.8, optional):** the Finnhub layer captures a
  16:30 UK benchmark for the US peers (1-minute candle → WebSocket trade →
  REST quote → Yahoo fallback, quality-tagged), refreshes their prices
  through the US session and attaches the latest company-specific news to
  material movers. Powers Market & Peers → "US since Europe closed".
  Runs only when `FINNHUB_API_KEY` (Actions secret) and `FINNHUB_ENABLED`
  (Actions variable) are set; without them every page keeps serving from
  Yahoo + stored data. Modes: `finnhub_anchor`, `finnhub_quotes`,
  `finnhub_news`, `finnhub_intraday` (see `scripts/refresh.py`).
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

## Finnhub setup & licensing gate (v2.8)

1. Create an API key at finnhub.io, then add it **manually** as the GitHub
   Actions secret `FINNHUB_API_KEY` (repo Settings → Secrets → Actions).
   Never commit a key, put it in YAML/source/tests, or paste it into chat —
   if a key is ever exposed, rotate it immediately.
2. Set Actions **variables** `FINNHUB_ENABLED=true` and
   `FINNHUB_USAGE_MODE=pilot`. Pilot mode restricts every Finnhub job to the
   evaluation universe in `config/finnhub.yaml` and labels the output as a
   provider evaluation alongside Yahoo.
3. `FINNHUB_USAGE_MODE=production` (full US universe) must stay off until
   Finnhub confirms in writing that the agreement covers: internal business
   use, display to the intended traders/analysts and user count, storage of
   intraday observations, storage/display of company-news metadata, display
   of derived peer-basket calculations, and the intended retention. Finnhub's
   listed self-serve plans are marked personal-use.
4. Everything is display-labelled *indicative market data* — it is not an
   execution-grade or guaranteed real-time feed.

Requests stay well inside the free tier: a conservative 30 req/min limiter
(`config/finnhub.yaml`), quotes only for the mapped US peers, news only for
material movers (|move since 16:30 UK| ≥ 1% plus top 5 each way, capped).

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
