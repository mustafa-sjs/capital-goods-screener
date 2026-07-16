# Changelog

## 2026-07-17 — v2.8.3 Coverage rows show "vs basket"
- Market & Peers: bold coverage-company rows now carry `rel_vs_basket_pct`
  (own 1-day move minus the peer basket's equal-weight average; the basket
  excludes the coverage name, so no self-dilution). Previously peer-only,
  leaving bold rows blank — most visible in tiny baskets (Rexel, Epiroc).
  `corr30` stays blank on coverage rows by design (self-correlation ≡ 1).

## 2026-07-17 — v2.8.2 Momentum backtest revamp & per-equity best setting
- **New crossover set** (user-selected): 5/30, 10/40, 10/60, 20/60, 20/100,
  20/120, 40/150, 50/200. Fresh backtest run: universe winner **50/200,
  confirm 5** (OOS Sharpe 1.31); no pair beat buy-and-hold out of sample —
  stated plainly on-page against a buy-and-hold column.
- **Per-equity evidence**: selecting a company (Stock Screener → Price
  Trend, and Company Analysis → Price Trend) now shows the setting that
  tested best on that share's own history (with apply/preselect) and a
  full comparison of every setting on that share — strategy vs buy-and-hold
  return AND drawdown, trades, win rate; min-trade guard flags anecdotes.
- **Drawdown fixes**: max-drawdown maths verified correct per security
  (three independent methods agree); the *portfolio* backtest previously
  zero-filled closed-market days, damping vol/drawdown — now excluded from
  the daily mean. OOS benchmark window aligned to the strategy window
  (warm-up tail excluded). Benchmark drawdown now stored/displayed
  everywhere a strategy drawdown is, and portfolio-level numbers are
  labelled as diversified-basket figures.
- **Strategy comparison rewritten** in plain English: what the strategy is,
  what the split means, one row per setting with buy-and-hold context.
- 128 tests (4 new: pair-set guard, benchmark drawdown, closed-market
  aggregation, per-metric checks).

## 2026-07-17 — v2.8.1 Forced-refresh button
- "Refresh data now" on Market & Peers and Data Status: dispatches the
  `us-intraday-market-data` workflow (plus optionally the daily price
  refresh) through the GitHub API using a fine-grained `GH_ACTIONS_TOKEN`
  from Streamlit secrets — the app still never calls market-data providers
  or holds the Finnhub key. Shared 10-minute cooldown recorded in
  `free_tier_usage`; extra presses get an explicit "you are rate limited"
  message. Workflow gained a `force` dispatch input (runs outside the
  scheduled window); `capture_anchor` exits early when today's 16:30 UK
  benchmark hasn't occurred yet. 124 tests (5 new, GitHub API mocked).

## 2026-07-16 — v2.8 Finnhub US intraday prices & catalyst context
Focused addition to Market & Peers — historical prices, canonical pipeline,
Yahoo daily refresh, peer baskets, fundamentals, momentum and the DB
abstraction are all unchanged. Finnhub is a second, licensing-gated US
market-data source, not a replacement.
- **"US since Europe closed" view** on Market & Peers: per-basket US tables
  (16:30 UK anchor price, current US price, move since 16:30, anchor
  quality, latest company-specific update, updated time), equal-weight peer
  summaries with best/weakest contributors, a coverage status strip, and
  clickable catalyst links for material movers. European rows never show a
  misleading 0.0% — closed markets show "–". Labelled *indicative market
  data*. The classic view's "since 16:30 UK" column now shows genuine US
  moves (previously it showed EU names' ~zero 16:30→close drift).
- **Hybrid 16:30 UK benchmark** (`market_benchmark_snapshots`, portable
  DuckDB/Postgres): finnhub_candle → finnhub_websocket → finnhub_quote →
  yahoo_intraday_fallback, each stored with real timestamps, source and
  quality (exact/acceptable/stale/unavailable, thresholds in
  `config/finnhub.yaml`); recovery runs only ever upgrade quality.
  `eu_close_snapshots` retained as the European compatibility path.
- **Catalyst layer** (`market_events`): company-news metadata for movers
  (≥1% since 16:30 or top 5 each way), deduplicated, transparently ranked,
  displayed as "Possible catalyst" / "Latest company-specific update" —
  never asserted causation; explicit "No recent company-specific catalyst
  identified" state.
- **Adapter & ops**: `src/ingestion/finnhub_market_data.py` (stdlib, token
  in header only, 30 req/min limiter, backoff+jitter, 401/403/429 typed
  handling), `src/features/us_intraday.py`, refresh modes `finnhub_anchor
  / finnhub_quotes / finnhub_news / finnhub_intraday`, workflow
  `us_intraday_refresh.yml` (DST-aware Python guards, own concurrency
  group), Finnhub section in Data Status, `data_version()` invalidates on
  new benchmark/catalyst data, cross-source Finnhub-vs-Yahoo checks.
- **Safety/licensing**: runs only with the `FINNHUB_API_KEY` Actions secret
  (never committed/logged; Streamlit never sees it) and `FINNHUB_ENABLED`;
  `FINNHUB_USAGE_MODE=pilot` restricts to an evaluation universe until
  commercial-use permission is confirmed. Without the key every page keeps
  serving from Yahoo + stored data.
- **Mapping**: `finnhub_symbol` added for all 48 US securities in the
  coverage pack (MOG/A → `MOG.A`), validated for gaps/duplicates/exchange/
  currency and surfaced in Data Status, never silently excluded.
- **Tests**: 119 total (30 new, all Finnhub traffic mocked — CI never calls
  the live API).

## 2026-07-14 — v2.7 Product simplification & consistency refactor
Incremental reorganisation — no calculation engine, database or refresh
change beyond the additions below; charts were moved and retitled, not
removed.
- **Navigation simplified** to five research destinations (Overview, Stock
  Screener, Compare Companies, Company Analysis, Market & Peers) plus
  Manage & Help (Watchlists, Data Status, Methodology, Legacy Dashboard).
  Former Momentum page → Stock Screener → Price Trend tab; Sector Rerating
  + Scenarios + Drill-Down → Company Analysis tabs; Signal Change Tape →
  Overview "Recent changes" + Data Status full history; Full Dashboard →
  Legacy Dashboard (retained until feature parity is confirmed).
- **Shared universe service** (`src/utils/universe.py: universe_service`)
  with hard validation (exactly 30 core incl. Siemens & Schneider, one
  primary listing and subgroup each); every page resolves membership
  through it. Universe selector (Core coverage default) now controls both
  display AND ranking populations — core ranks are calculated across core
  only, never filtered from full-universe ranks.
- **Central metric dictionary** (`src/utils/metrics.py`): display name,
  plain-English definition, format, category, higher-is semantics for every
  user-facing metric; all tables/filters/tooltips resolve through it. Raw
  internal names (rel_3m_pct, Hist z, ρ30, c5, OOS…) no longer reach the UI.
- **Momentum unified**: one engine (pair_features on canonical TR history,
  config default pair) feeds engine payload, screener, heatmap, company
  page and events. The overloaded "bullish" label is replaced by three
  fields everywhere: **Trend** (Uptrend/Downtrend/No clear trend),
  **Momentum change** (Strengthening/Stable/Weakening — 5-session change in
  EWMA distance), **Recent signal** (confirmed crossover within 15
  sessions). Heatmap defaults to 4 columns on core coverage (expanded view
  optional). Backtest presented honestly: "best-tested trend setting",
  did-not-beat-buy-and-hold caveat, sample sizes on all evidence.
- **New pages**: Compare Companies (2–5 names side by side + indexed TR
  chart + valuation-history overlay, reusing existing data), Methodology
  (metric dictionary, trend definitions, score weights, full docs).
- **Design system**: restrained page headers with one-line purpose,
  compact data-status strip on every market page (market date, core
  freshness, financials basis, updated time, ⓘ tooltip), colour semantics
  split (green/red = performance/fundamentals only; blue = cheaper, orange
  = more expensive; amber = warnings), chart titles rewritten as the
  question each chart answers, quadrant explanation on the positioning map.
- **Data Status** translates validation findings and change events into
  plain English; run IDs/raw checks/DB tables moved into an Administration
  expander. Overview shows consequences, not pipeline internals.
- Tests 58 → 89: universe consistency (30 core, SIE/SU, one listing/
  subgroup each, payload agreement), metric-registry completeness & no
  internal labels in defaults, momentum consistency (payload == engine,
  core-only ranks, controlled vocabularies, signal-date agreement), page
  smoke tests for all nine pages via streamlit AppTest, cross-page price
  consistency (screener == scenarios == market close).

## 2026-07-13 — v2.6 Freshness: core-coverage momentum default + reliable price pipeline
- Momentum universe defaults to core coverage; freshness validation gate
  (stale core names block publication); prices_only rebuilds features so a
  stale snapshot is never republished as new (see commit a07b88e).

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
