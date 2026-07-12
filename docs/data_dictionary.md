# Data dictionary (condensed)

Full schema with keys/constraints: `src/database/schema.sql` (the authority).
Metric definitions & methodology: `capital_goods_methodology.md`.

| Table | Grain / key | Content & lineage |
|---|---|---|
| securities | key | identity, currencies, retrieval symbols (config-sourced) |
| coverage_groups / coverage_members | group_id (+key, role) | curated pack structure — source of truth is config YAML |
| raw_daily_prices | key, price_date, source | OHLCV; sources: 'factiq' (history), 'mixed' (yahoo-merged), 'manual_csv' |
| raw_monthly_prices | key, price_date, source | month-end closes (FactIQ, ~8y) |
| raw_quotes | key | latest close/prev/52w (refresh overwrites; history lives in daily) |
| raw_fx_rates | pair, rate_date, source | vs-USD closes |
| eu_close_snapshots | key, obs_date, benchmark_time | TRUE 16:30 UK price + later close; DST-aware |
| raw_fundamentals | key, kind | FactIQ/SEC statement payloads verbatim (JSON) |
| raw_estimate_snapshots | key, snapshot_date, metric, period | EMPTY by design — no consensus source; ready for one |
| feat_screener | snapshot_date, key | full screener row JSON + indexed columns; accumulates daily (point-in-time) |
| feat_close_rows/groups | snapshot_date, ... | read-across page data per snapshot |
| feat_scenarios | snapshot_date, key, scenario | mechanical scenarios (labelled) |
| feat_valuation_history | key, year | approximate annual EV/EBITDA (documented look-ahead caveat) |
| app_payload | snapshot_date | full engine JSON (app + embedded dashboard) |
| watchlists / watchlist_members | id (+key) | user lists, notes, thesis status |
| refresh_runs / refresh_run_items | run_id (+item) | audit trail of every refresh |
| validation_results | run_id, check, subject | severity-tagged findings; nothing auto-deleted |
| daily_change_events | snapshot_date, key, event_type | diffs between consecutive snapshots |
| free_tier_usage | as_of, metric | usage readings for the Admin panel |

Retention: raw + features accumulate (tiny: ~11MB total today, +~2MB/year);
operational logs prunable after 90d; parquet archives mirror everything.
