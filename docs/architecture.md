# Architecture

## Target (implemented)

```
GitHub private repo  ──  code, config, docs, RAW DATA FILES (versioned), workflows
      │
      ├── GitHub Actions (free linux runners)
      │     daily-refresh    22:12 UTC weekdays: Yahoo prices → engine →
      │                      validation gate → Supabase publish → commit data
      │     intraday-eu-close 16:36 London (DST-aware): true 16:30 UK snapshots
      │     tests / backup   PR-gated pytest; weekly parquet artifact (7-day)
      │
      ├── Supabase Free Postgres  ── production DB (same schema as local)
      │
      └── Streamlit Community Cloud ── private app, 9 pages + embedded
                                       original dashboard; reads precomputed
                                       tables only (no heavy work on load)

Local dev = identical code against data/capital_goods.duckdb + parquet archive.
FactIQ (fundamentals/statements) = interactive Claude session only, by design.
Yahoo = replaceable adapter (src/ingestion/base.py); ManualCSV fallback.
```

## Four data layers

1. **Raw** — `data/raw/*.json` exactly as received (git-versioned) plus
   `raw_*` DB tables (prices, quotes, FX, fundamentals payloads, EU snapshots).
2. **Normalised** — currently inside the engine (`scripts/compute_metrics.py`
   standardises currencies, periods, LTM sums, EV construction).
   A separate `normalised_financials` table is the Phase-4 refactor.
3. **Features** — engine output published per snapshot_date: `feat_screener`,
   `feat_close_*`, `feat_scenarios`, `feat_valuation_history`. One trusted
   definition per metric; snapshots never overwritten → point-in-time audit.
4. **Presentation** — `app_payload` (full JSON the app and the embedded
   dashboard read); Streamlit pages do zero recomputation.

## Dependency graph (what a change recalculates)

- **New daily price** → engine recompute (mcap, EV, multiples, returns,
  momentum, correlations, read-across, screener) — statements NOT re-fetched.
- **New financial result** (FactIQ session) → raw payloads → same engine pass.
- **Peer-map change** (`config/coverage_packs/*.yaml`) → `refresh.py --mode
  rebuild_features` only — nothing re-downloaded.
- **New consensus source** (future) → `raw_estimate_snapshots` is ready;
  engine gains a forward-basis branch; screener flips off LTM fallback.

## Deviations from the default architecture (explained)

- **The original rich dashboard is kept** as a self-contained HTML artifact
  and embedded in Streamlit (page 9) rather than being rewritten as native
  Streamlit charts. Conversion would materially reduce functionality
  (six validated interactive pages, ECharts) for zero reliability gain.
  The other 9 Streamlit pages provide everything the HTML cannot (DB-backed
  watchlists, daily-change auditing, admin, presets).
- **Raw data files live in git** (2.7 MB, small daily diffs). This gives
  free versioned point-in-time history and makes every clone reproducible;
  Supabase holds the same observations for the live app.
- **Stable keys are TEXT** (`ABBN`, `MRO`) not integer ids — they already
  function as internal identifiers decoupled from tickers/listings, and
  human-readable keys keep every table and config auditable.
