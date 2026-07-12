# Changelog

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
