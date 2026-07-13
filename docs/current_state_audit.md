# Current-state audit — 2026-07-13 (pre-v2.3 work)

Method: every claim below verified against code on branch `research-os`
(baseline commit 174aeda, 30/30 tests passing), not against documentation.

## Working and wired into production
- Canonical daily price history (5y, 98.8k sessions; raw / split-adjusted /
  total-return bases; exchange-timezone session dates) — `data/history/*.parquet`
  + `canonical_prices` DB table. **Verified.**
- Corporate-action capture (1,064 dividends/splits incl. VISN $10 special). **Verified.**
- Session-aware calendar + trading-session returns with exact windows
  (`src/features/returns.py`), regression-tested against independent values. **Verified.**
- EWMA momentum engine + separate valuation/fundamental/momentum states. **Verified.**
- Screener presets (state-aware YAML rules), drill-down with basis toggle +
  EMA overlays, watchlists (basic), snapshot history in `feat_screener`,
  validation framework with CRITICAL publish gate, refresh audit trail. **Verified.**
- Free-tier deployment: GitHub Actions + Supabase + Streamlit Cloud; no paid
  services. **Verified.**

## Implemented but defective or not wired into production (fixed in v2.3)
1. **Daily refresh ran the FULL 5-year backfill every run**
   (`scripts/refresh.py` → `backfill_history.py`, no incremental mode).
   Wasteful (79×5y fetches/day) and fragile (one Yahoo outage risks the whole
   history file). → split into incremental (1-month window + overlap
   reconciliation) with automatic full-rebuild trigger when new corporate
   actions invalidate stored total-return scaling; explicit repair/full modes.
2. **Ordinary production refresh never published canonical prices** —
   `refresh.py`'s publish step loaded raw prices/quotes/FX/features but not
   `load_canonical`. Supabase only got canonical data from manual migrations.
   The cloud app could therefore chart different data than the screener
   metrics. → fixed; publication includes canonical + actions + reconciliation.
3. **Drill-down charts read committed parquet directly**, not the database —
   two sources of truth (local file vintage vs DB snapshot). → DB-first with
   labelled parquet fallback for development.
4. **No row-level provenance**: canonical rows lacked run_id; reconciliation
   results lived only in a CSV; raw merged Yahoo rows were labelled source
   `mixed`. → run_id stamped through; `price_reconciliation` table added;
   provider labels preserved.
5. **No candidate-vs-production comparison before publish**: validation ran
   against whatever was in the DB, then features were loaded regardless of
   how they compared with the previous snapshot. → publish gate now checks
   universe-coverage drop, snapshot regression, canonical staleness and
   feature-vs-price date consistency before loading features.

## Implemented but semantically misleading (fixed earlier, re-verified)
- classify() mixing fundamentals into "momentum" labels — fixed v2.2.
- "114 securities" headline (basket slots) — fixed v2.1/v2.2.
- Repeated validation warnings per run — deduplicated views v2.2.

## Planned, NOT implemented (documented roadmap, no code)
- Quality & capital-allocation page; Historical Metric Explorer;
  Relative-Value Pairs Lab; quality-adjusted valuation regression —
  all require the normalised-fundamentals layer (statements are stored raw;
  only engine-level LTM aggregates exist today).
- SEC point-in-time fundamentals (filing dates) — highest-value data item;
  prototype path in docs/free_data_capability_matrix.md.
- Insider transactions (Form 4), 13F, ESEF, macro overlays — assessed in the
  free-data matrix, none integrated.
- Historical screen replay / backtesting — blocked on PIT dates for
  fundamentals; price-only replay possible once feature snapshots accumulate.
- Nested AND/OR custom-screen groups — v2.3 ships flat-AND conditions with
  save/load/export; nesting documented as future work.

## Known two-sources-of-truth risks (state after v2.3)
- `data/raw/daily_*.json` (FactIQ + merged Yahoo top-ups) still exists for
  engine inputs and correlation fallback; canonical parquet/DB is authoritative
  for all returns/momentum/charts. Documented; reconciliation table tracks
  cross-source conflicts (173 known, mostly Nordic line differences).
- Engine's SEC/SUBGROUPS literals vs config YAML — guarded by an equality test.

## Unable to verify
- Streamlit Cloud runtime behaviour beyond import/smoke (verified via local
  identical versions; the cloud redeploys from main on push).
- Yahoo adjclose dividend completeness for every non-US name (spot-checked;
  full-rebuild cadence self-heals late postings).
