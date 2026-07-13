# FactIQ capability matrix (verified during the 2026-07 build; re-verify per session)

Everything below was established by live queries during the original build
(catalog, search_datasets, run_sql probes, get_market_data calls across
European, UK, US and Japanese names). FactIQ is interactively authenticated,
so automated runners cannot query it; refresh via a Claude session.

| Dataset / endpoint | Fields | Periodicity | Depth | Coverage | PIT dates? | Quality limits | Screener use | Priority |
|---|---|---|---|---|---|---|---|---|
| get_market_data GLOBAL_QUOTE | close, prev, 52w range | live/EOD | current | all 79 | n/a | official close only, no intraday | quotes (superseded by Yahoo daily) | done |
| get_market_data TIME_SERIES_DAILY | OHLCV | daily | ~4.5mo visible | all 79 | dates | **intelligently sampled** (~50 rows/call) | raw cross-check only | done |
| get_market_data TIME_SERIES_MONTHLY | close | monthly | ~8y | all 79 | dates | sampled; month labels ≠ month-end | annual valuation charts ONLY | done |
| get_market_data INCOME_STATEMENT / BALANCE_SHEET / CASH_FLOW | full statements | annual (+ some quarterly) | 5-20y | non-US names | filing yr only | EU quarterlies sparse; fields vary by filer | fundamentals layer (in prod) | done |
| sec schema (EDGAR XBRL, SQL) | tagged financials, LTM-able quarters, **filed_at dates** | quarterly | 10y+ | 37 US filers (verified 2026-07-13: filings table lacks ATKR, BDC, BMI, GBX, HXL, KMT, MOGA, OSK, TEX, TKR, VISN) | **YES — implemented** | tag gaps (op income, debt for some) | PIT layer live: filing_dates table + src/features/pit.py | **DONE (v2.4)** |
| sec_kpi dataset | co-specific KPIs | quarterly | varies | US >$10bn only | partial | NO orders/backlog for EU names | not usable pack-wide (documented) | none |
| search_earnings claims/pressure_points | quote-anchored call intelligence | per call | recent qtrs | US callers | call date | qualitative; US-centric | drill-down annotations via session | MEDIUM |
| FX_DAILY | fx closes | daily | years | majors | dates | none material | in prod | done |
| Consensus estimates / revisions / surprises / analyst counts | — | — | — | — | — | **DOES NOT EXIST anywhere in FactIQ** | revisions module stays disabled, never faked | n/a |
| Order intake / backlog / book-to-bill | — | — | — | — | — | not provided for this universe | **not proxied** (hard constraint) | n/a |
| Guidance text | US filers | per filing | recent | US subset | filing date | unquantified text | possible drill-down annotation | LOW |

## Highest-value unexploited item

**SEC XBRL filing dates** enable true point-in-time fundamentals for the 37
US names — the missing ingredient for backtesting valuation signals on half
the universe. Implementation: store `filed_date` alongside each LTM row
(one extra SQL column), then historical screens for US names can use only
data available at each date. European names have no PIT filing-date source
in FactIQ; their historical screens stay approximate and labelled.

## Token-cost note

A full statements refresh (~90 calls with rate-limit sleeps) is the main
recurring FactIQ cost; quarterly cadence keeps it trivial. Catalog probing
is one-off per capability question.
