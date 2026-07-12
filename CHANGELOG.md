# Changelog

## 2026-07-13 — v2.2 Price engine & momentum
- ROOT-CAUSE FIX: 1M-12M returns were computed against partial-month monthly
  samples (~10-day "1M"); 5D used a calendar stretch. Replaced by canonical
  5y daily history (exchange-timezone sessions, raw/split/total-return bases,
  1,064 corporate actions) and session-aware return functions with exact
  windows. ABBN 1M -4.57% -> +5.00%; full audit in docs/price_data_audit.md.
- VISN 2026-04-28 recognised as a $10 special distribution (TR basis), not a crash.
- EWMA momentum engine (10/30, 20/60, 50/200; explicit states, descriptive-only
  labels), 12-1 momentum, EW vol, drawdowns; docs/momentum_methodology.md.
- classify() split into separate valuation / fundamental / momentum states;
  presets rebuilt on states; premiums list no longer shows discounts;
  validation findings deduplicated; drill-down price-basis toggle + EMA
  overlays + action markers + exact return windows.
- 30 tests (was 14) incl. audit regressions, synthetic calendars, VISN action.

## 2026-07-12 — v2.0 Platform migration
- Git repository initialised; config-driven universe (coverage-pack YAML as
  single source of truth with tested engine-literal fallback).
- Persistent DB: portable schema (DuckDB dev / Supabase Postgres prod),
  idempotent loader, parquet archives, backup/restore scripts.
- Incremental pipelines: adapter interface (Yahoo/ManualCSV/Mock), single
  refresh command with modes, refresh-run audit trail, validation gate
  (CRITICAL blocks publication), true 16:30 UK intraday snapshots.
- Streamlit app: 9 pages + embedded original dashboard, presets, watchlists,
  daily changes, admin + free-tier panel.
- GitHub Actions: daily refresh, DST-aware intraday, tests, weekly backup —
  free-tier guarded. 14 unit/data-quality tests.
- Calculation changes: NONE (engine untouched this release; v1.1 bridge fix
  below is the latest calculation change).

## 2026-07-12 — v1.1
- Scenario decomposition made exactly additive (equity-level effects).
- Drill-down peer tables show full LTM multiples; Yahoo incremental price
  refresh + launchd daily schedule.

## 2026-07-11 — v1.0 Initial build
- 114 securities resolved/validated; engine, 5 CSVs, methodology, 6-page
  dashboard; LTM-only basis (no consensus feed); QA'd twice.
