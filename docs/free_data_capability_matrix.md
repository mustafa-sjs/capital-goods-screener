# Free data capability matrix (assessed 2026-07-13)

Assessment criteria: coverage of THIS universe, reliability, PIT availability,
rate limits/licensing, maintenance cost, capital-goods relevance. Nothing
below is integrated yet — this is the vetted queue. No paid services.

| Source | What it gives | Universe fit | PIT? | Effort | Priority | Verdict |
|---|---|---|---|---|---|---|
| SEC EDGAR APIs (companyfacts, submissions JSON; bulk ZIPs) | filing-date-aware XBRL fundamentals, earnings/filing dates, restatements | 37/79 (US names) | **YES — filing dates** | Medium (declared User-Agent, ~10 req/s cap, cache locally) | **P1 — highest value** | The unlock for legitimate US backtesting and historical screens. Prototype: store `filed` date per LTM quarter alongside existing sec-schema data. |
| SEC Forms 3/4/5 (insider) | open-market purchases vs option exercises/auto-sales; cluster buying; buys-after-drawdown | 37/79 | yes (accepted dates) | Medium (parse form XML from EDGAR full-text index) | P2 | Useful overlay for US names only; must separate routine comp from real buying; never extended to EU names. |
| SEC 13F | quarterly institutional ownership deltas, new/exiting holders | 37/79 | 45-day lag, disclosed | Medium-high | P3 | Lag + US-only limits value; do after insiders. |
| filings.xbrl.org (ESEF) | structured European annual reports | EU names, ANNUAL only, variable tagging quality | partial (filing dates exist) | High (taxonomy variance across countries) | P3 research | Start with 3-5 representative companies (SU, SIE, ABBN via SIX?, VOLVB) before committing; annual-only limits screener use. |
| Companies House API (free key) | UK filing dates, accounts due, status, charges | 8 UK names (legal-entity level) | yes | Low | P3 | Metadata only — NOT comparable standardised financials; useful for filing-calendar nudges. |
| ECB SDMX / Eurostat / FRED | FX, rates, industrial production, credit conditions | macro overlay | yes | Low | P3 | Only with a concrete use case (rate-regime split for backtests; FX-adjusted relative performance). Avoid decorative macro. |
| Company IR calendars | earnings dates, CMD dates | all | n/a | High (brittle scraping) | Deferred | Prefer SEC submissions dates for US; EU dates entered manually per watchlist (catalyst_date field ships in v2.3). |
| Yahoo endpoints (already integrated) | prices, adjclose, dividends/splits | 79/79 | n/a | done | done | Canonical price source since v2.2. |

## Recommended sequence
1. **SEC filing dates** into the existing sec-schema LTM pipeline (one column),
   enabling PIT US fundamentals → unlocks Phase-17 style backtesting for half
   the universe honestly.
2. Form 4 net-open-market-purchase features (30/90/180d) for US names,
   clearly restricted and labelled.
3. ESEF feasibility spike on 3 names; go/no-go documented.
