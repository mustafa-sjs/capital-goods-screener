# Price-data audit — root-cause report (2026-07-13)

## Verdict

The dashboard's 1M/3M/6M/12M returns were **materially wrong by construction**,
and 5D was approximate. Latest closes were correct. Root causes, confirmed in
`scripts/compute_metrics.py` (`px_return`, now retired):

1. **Partial-month anchor.** Monthly returns used the FactIQ *monthly* series,
   whose newest row is the current **partial month**. "1M" compared the
   latest close against the previous month-end — a ~10-day window labelled
   as a month. Every "1M" printed since launch measured month-to-date, which
   is why old 1M values were systematically ~5–10pp more negative than truth
   in a rising tape (see table below).
2. **Month-start labelling + nearest-date pick.** The comparison row was
   chosen by minimum date distance to a month-start label, so "12M" could
   anchor on either side of the intended date depending on sampling.
3. **Sampled series.** FactIQ price series are intelligently sampled (~50
   visible rows); nearest-date matching on a thinned series adds noise.
4. **5D calendar stretch.** 5-day returns used `days × 1.45` calendar
   conversion instead of counting 5 actual sessions — wrong around holidays
   and mid-week weekends.
5. **No corporate-action awareness.** VISN's 2026-04-28 −49% "move" is a
   **$10.00 special cash distribution** (confirmed in the corporate-action
   feed), not a crash. Raw-price momentum treated it as one.
6. **Timestamp handling.** Session dates were derived as
   `UTC + fixed gmtoffset`; now derived in each exchange's own timezone
   (`exchangeTimezoneName` + `zoneinfo`), DST-correct.
7. **Session-completeness guard.** The prior guard compared
   `regularMarketTime < regular.end`, which mis-dropped completed sessions
   on markets whose last print lands seconds before the official close
   (found: all SIX names lost their final session). Now: a session is
   in-progress only if *now* falls inside [start, end).

## Fix

- **Canonical layer**: `data/history/prices_daily.parquet` — 98,765 completed
  sessions (5y × 79 securities, ~1,250/name; ≥252 for 1y indicators, ≥504
  for 2y), exchange-timezone dated, with `close_raw`, `close_split`,
  `close_tr` (total-return) and `corporate_actions.parquet` (1,064 dividends
  & splits). FactIQ raws retained untouched in `raw_daily_prices`;
  cross-source conflicts >0.5% written to `data/audit/price_reconciliation_*.csv`
  (173 rows, dominated by Nordic names where FactIQ used LSE order-book
  lines vs native OMX lines — a line difference, not an error; plus HON,
  where FactIQ's line shows stale sampling. Canonical selection = yahoo5y
  for density + adjustment data; reason recorded per file).
- **Session-aware returns** (`src/features/returns.py`): session horizons
  (1D/5D/21D/63D/126D/252D) count exact sessions on the security's own
  calendar; calendar horizons (1M/3M/6M/12M) roll back to the last session
  on or before the same calendar date N months earlier. Both definitions
  displayed and documented; every result carries its actual window,
  session count and status.
- **Bases separated**: raw for displayed price moves & raw charts; split-
  adjusted for continuity ex-dividends; **total-return for all momentum and
  relative comparisons** (drill-down has a three-way toggle).

## Regression checks (arise from the functions, not hard-coded — tests enforce)

| Check | Old dashboard | Corrected | Independent expectation |
|---|---|---|---|
| ABBN 1M @2026-07-10 | −4.57% | **+5.00%** (2026-06-10→07-10, 22 sessions) | +5.00% (83.58 vs 79.60) |
| ABBN 3M | +6.55% | **+16.34%** (2026-04-10→07-10) | +16.34% (vs 71.84) |
| LR 1M | −4.74% | **+3.15%** (vs 136.40) | +3.15% |
| LR 3M | −7.31% | **−5.48%** (vs 148.85) | −5.48% |
| VISN 1D @2026-04-28 | −49% "crash" | raw −49.3% / **TR −0.6%** | $10 special distribution |

## Before/after, 13-security sample (full CSV: data/audit/before_after_returns.csv)

Old 1M was wrong-signed for 10 of 13 names. Largest distortions: RR 1M
−0.4%→+16.6%; EBARA 1M −2.1%→+16.4%; ETN 1M −4.4%→+8.5%; VISN 12M
−30.6%→+58.9% (raw, dense series) — and VISN relative momentum now uses TR.

Audited sample covered CHF (ABBN), EUR (LR, SU, METSO, PRY), GBp (MRO, RR),
SEK (VOLVB, ATCOA), JPY (EBARA), USD (ETN), share-class (MOG-A) and the
special-distribution case (VISN). Ticker→listing mapping verified against
exchange/currency/timezone metadata per name; no mismatches found (Nordic
line differences documented above).

## Residual limitations

- Yahoo `adjclose` is the total-return source; its dividend coverage for
  some non-US names can lag a few days after ex-date.
- FactIQ sampled daily rows remain in the DB as a second raw source only.
- The monthly series still powers the coarse annual valuation charts —
  and nothing else.
