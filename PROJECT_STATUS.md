# PROJECT STATUS — Capital Goods Research Platform

*Updated 2026-07-12 (update this file whenever the facts below change).*

| Fact | Value |
|---|---|
| Local project root | `/Users/Mustafa/capital-goods-dashboard` |
| Git repository | github.com/mustafa-sjs/capital-goods-screener (private), pushed 2026-07-12 |
| Production app URL | https://capital-goods-screener.streamlit.app (Streamlit Community Cloud, deployed 2026-07-12) |
| Production database | Supabase Free — project `vsypgmhndqoxklujxrep` (eu-west-2), migrated 2026-07-12, 23 tables verified |
| Dev database | `data/capital_goods.duckdb` (~11 MB) + `data/archive/*.parquet` |
| Version / commit | run `git log --oneline -1` |
| Last successful price refresh | 2026-07-12 (mode=daily, 84/84 ok — see `refresh_runs`) |
| Last financial-data refresh | 2026-07-11 (FactIQ statements, all 79 names) |
| Last estimate refresh | n/a — **no consensus source exists**; revisions module disabled, not faked |
| Coverage / peers | 30 coverage names, 114 basket slots, 79 unique securities |
| Unresolved securities | 0 (Crane NXT proxy flagged `medium`; VISN resolved, multiples NM) |
| Database size | ~11 MB local (Supabase free limit 500 MB — ~2% when migrated) |
| Known data-quality issues | VISN restructuring distortions; Crane proxy; captive-finance EV flags; sampled FactIQ price history pre-2026-06; GBp units; see `validation_results` |
| Current phase | Phase 2 complete (persistent + reliable updates); Phase 3 largely complete (screener/presets/changes/watchlists); Phase 4 (backtesting) roadmap only |
| Limitations | LTM-only basis (no consensus feed); own-history percentiles on 3–6 annual obs; EU-close read-across uses full-session closes until intraday workflow accumulates snapshots |

## Next three priorities

1. **User connects the free accounts** (GitHub push, Supabase, Streamlit) — exact steps in `docs/deployment.md`.
2. Accumulate daily + intraday snapshots for 2–3 weeks, then activate the Daily-Changes review habit.
3. Normalised-fundamentals layer (`normalised_financials`) to unlock quality-adjusted valuation residuals (signal family F).

## Required user actions

See `docs/deployment.md` — GitHub repo creation + push, Supabase project +
`DATABASE_URL` secret, Streamlit Cloud app + secrets. Nothing else is blocked.
