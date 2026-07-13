# Changelog

## 2026-07-13 — v2.5 Momentum screener & EWMA backtest
- History deepened to 10 years (191k sessions, 1,982 corporate actions,
  retry/backoff hardened backfill; coverage report in data/audit/).
- New Momentum page: filter bar, 6 summary cards, cross-sectional percentile
  heatmap, ranked screener with per-name signal history (sample sizes shown),
  plotly detail chart (TR price, EMA overlays, crossover markers, log toggle),
  collapsed OOS strategy comparison with apply-pair.
- Backtest engine (src/screening/backtest.py): vectorised long-only crossover
  strategy, confirmation windows, 25bps/side costs, next-close execution,
  IS/OOS split, robust ranking with decay/dominance/turnover penalties.
  Honest result: no pair beat buy-and-hold OOS; documented.
- config/momentum.yaml single source (spans, pairs, costs, score weights);
  momentum_backtest_results table; weekly backtest via Actions. 52 tests.

## 2026-07-13 — v2.4 Point-in-time layer (SEC filing dates)
- Fetched 916 filing dates (10-K/10-Q, 2020->present) from FactIQ's SEC
  filings table for 37 US names; persisted to data/raw/sec_filing_dates.json
  and the new filing_dates table.
- src/features/pit.py: fundamentals_asof(key, date) returns the latest period
  that was PUBLIC on that date — the no-look-ahead primitive for honest
  historical screens/backtests on the US half of the universe. Coverage gaps
  (11 US lines absent from the feed; all European names) explicitly labelled
  'pit_unavailable', never guessed.
- Drill-down provenance now states each name's PIT status and filing lag.
- 5 new tests incl. the critical between-filings look-ahead case. 44 total.

## 2026-07-13 — v2.3 Research OS: pipeline integrity + analyst workflow
- Refresh split: daily = INCREMENTAL canonical update (1-month window, overlap
  reconciliation, automatic per-security full rebuild when new corporate
  actions land); full_refresh = complete 5y rebuild; repair mode for named keys.
- Candidate-to-production gate: coverage-drop / snapshot-regression /
  feature-vs-price-date / canonical-staleness / missing-history /
  multi-currency checks run BEFORE features publish; CRITICAL blocks.
- Canonical prices + corporate actions now published to production on every
  ordinary refresh (previously only via manual migration).
- Drill-down charts are database-first (canonical_prices) with a labelled
  parquet fallback; source + latest-session caption displayed.
- Provenance: run_id stamped through canonical rows; price_reconciliation
  table; overlap conflicts recorded per run.
- NEW Signal Change Tape page: typed deterministic events (state changes,
  discount thresholds/moves, 52w highs, drawdowns, EMA crossovers, leverage/
  sign flips, data-quality changes, universe entry/exit) with prev/current
  values, consolidation (first/last/count), filters and CSV export.
- Custom screen builder: flat-AND conditions over numeric + state metrics,
  saved to the database, loadable/deletable/exportable; column-layout presets
  (Standard/Valuation/Quality/Momentum/Custom) on the screener.
- Watchlist thesis monitoring: thesis/bull/base/bear, catalyst + date,
  invalidation, review date; thesis-change log; deterministic triggers
  (catalyst approaching, review due, momentum/leverage conditions) labelled
  "requires review", never advice.
- docs/current_state_audit.md, docs/free_data_capability_matrix.md; 39 tests.

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
