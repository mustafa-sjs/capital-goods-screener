# Capital Goods Dashboard — Methodology

Generated 2026-07-11/12 from FactIQ MCP data (market-data provider + SEC EDGAR
XBRL schema). All computation code lives in `scripts/compute_metrics.py`;
edit `capital_goods_peer_map.yaml` and re-run it to change the universe.

## 1. Security mapping

Every security was resolved through the provider symbol search and validated
by echoing the live quote (name / exchange / MIC / currency). The full table
is `capital_goods_security_mapping.csv`. Key decisions:

- **Nordic and Helsinki names** are priced through their LSE international
  order-book lines (e.g. Volvo B = `0HTP:LSE`, Atlas Copco A = `0XXT:LSE`),
  which quote in native SEK/EUR. Same issuer, same currency; provider direct
  OMX symbols were not resolvable.
- **Vistance Networks (“VISN” in the source material)** resolved cleanly to
  Vistance Networks, Inc., NASDAQ (XNGS), USD. It was *not* substituted.
  Its financials show a major restructuring (negative equity during 2024-25,
  a large one-off tax benefit, a distorted quarterly revenue line), so all
  earnings-based multiples are shown NM and the name carries a data-quality
  flag wherever it appears.
- **Crane Co**: the provider’s `CR` line carries Crane NXT statements after
  the 2023 separation. It is used as an **approximate proxy** and flagged;
  treat Crane-based peer stats with caution.
- **GE** = GE Aerospace post the 2023-24 three-way split; pre-2024 history
  is not comparable and is flagged.
- **Schindler** uses the participation certificate (SCHP), the standard
  reference line. **Moog** uses the class-A line (MOG.A).
- GBp (pence) quotes are converted to GBP (÷100) before any market-cap math.

## 2. Estimate basis — why everything is LTM

The requested hierarchy (NTM EV/EBITA → NTM EV/EBITDA → FY1 → FY1 P/E →
NTM FCF yield → LTM EV/EBITDA) was applied. FactIQ exposes **no consensus
estimates, no estimate revisions, no analyst counts and no earnings
surprises** (confirmed against the data catalog: SEC EDGAR carries reported
XBRL and company guidance text for US filers only; the market-data provider
carries reported statements). Therefore:

> **Every comparison in this dashboard uses the LTM reported fallback.**
> `estimate_basis = "LTM reported fallback"` on every row. No peer median
> mixes NTM and LTM — the basis is uniformly LTM.

Consequences:
- The **earnings-revisions module is disabled** (Page 3 columns show n/a and
  the drill-down states the limitation). Momentum context comes from price
  performance and from reported growth (latest FY vs prior FY) instead.
- Earnings surprises and guidance-change tracking are likewise disabled
  (guidance text exists only for US filers and is not quantified consensus).

## 3. Financial definitions

All fundamentals are kept in each company’s **reporting currency**; market
cap is converted into that currency at the spot FX (provider FX series,
timestamp in the JSON payload) before EV is formed.

- `EBITDA = operating income + depreciation & amortisation` where both are
  reported; otherwise the provider’s `ebitda` column. EBITA is not reported
  separately by these sources, so EV/EBIT (operating income) is shown as the
  closest EBITA proxy, labelled EV/EBIT.
- `Free cash flow = operating cash flow − capital expenditure` (annual CF
  statement, or LTM sum for SEC names).
- `Net debt = short-term debt + long-term debt − (cash + cash equivalents +
  short-term investments)`. Leases are included only where the filer folds
  them into debt.
- `EV = market cap (report ccy) + net debt + minority interest`.
- US names covered by the SEC XBRL schema use LTM sums of the last four
  quarters. Where a filer does not tag operating income (ETN, EMR, GE, JCI,
  DE, KLAC, WWD, COHR, PCAR), **EBIT is reconstructed as LTM pretax income +
  interest expense** and flagged. Where debt/cash tags are missing (CAT, GE,
  EMR-cash, PCAR), EV is built from what exists and flagged — those EVs are
  understated/overstated accordingly.
- **Captive finance** (CAT, DE, PCAR, Volvo, Daimler Truck, Traton):
  consolidated net debt includes financial-services funding, so EV/EBITDA is
  not comparable with “industrial-only” conventions. Flagged on every row.
- `NM` is shown when a denominator is negative, missing, or < 2 % of the
  numerator. Nothing is zero-filled.

## 4. Peer / sector / history layers

- **Direct peers**: curated baskets from `capital_goods_peer_map.yaml`
  (never automated classifications). Median is the primary benchmark;
  quartiles, min/max, percentile rank and distances are computed on the
  members with valid values (count shown).
- **Wider sector**: all unique tickers in the pack, **deduplicated** (Emerson
  counts once no matter how many baskets it sits in). Equal-weighted median
  by default; a market-cap-weighted median (weighted 50th percentile on USD
  market caps) is also computed.
- **Own history**: fiscal years 2020-2025. For each year,
  `EV_y = year-end price × that year’s diluted shares × year-end FX +
  that year-end’s net debt (+ minority)`, divided by that fiscal year’s
  EBITDA. This is an **approximate point-in-time** series: it uses reported
  fiscal-year fundamentals (not consensus, which does not exist here) and
  month-end prices from a sampled monthly series. Percentile, z-score,
  median/mean, quartiles, min/max are computed on those annual observations
  (3–6 points per name — treat percentiles as coarse).
- Look-ahead bias: year-end price vs fiscal-year fundamentals implies the
  fundamentals were only partially known at the price date. This is the
  standard trade-off absent point-in-time estimate vintages, and is why the
  series is labelled *approximate* everywhere it appears.

## 5. Price data, returns and correlations

- Quotes are official-close snapshots (2026-07-10 close for Europe/US;
  Tokyo 2026-07-10 local). Daily series ≈ last 4.5 months; monthly series
  ≈ 8 years. Both are **intelligently sampled** by the API (recent rows
  dense, older rows thinned): returns use nearest-date matching and
  correlations use shared adjacent-session log returns only, with `n_obs`
  reported next to every correlation.
- Returns (since 2026-07-13) come from the CANONICAL 5-year daily history
  (data/history/prices_daily.parquet; exchange-timezone session dates,
  complete sessions only). Session horizons (1D/5D/21D/63D/126D/252D) count
  exact trading sessions; calendar horizons (1M/3M/6M/12M) roll back to the
  last session on or before the same calendar date N months earlier.
  Displayed price moves are RAW; momentum and relative comparisons are
  TOTAL-RETURN (dividends/specials reinvested). The previous monthly-series
  method was materially wrong (docs/price_data_audit.md) and is retired.
- 30d/90d correlations: Pearson on shared-date log returns within 45/130
  calendar-day windows (minimum 8 shared observations, else blank).

### 5b. Incremental price refresh (secondary source)

`scripts/refresh_prices.py` tops up the recent end of the price data without
re-fetching history: one Yahoo Finance chart-endpoint call per security (no
API key) refreshes the live quote (close / previous close / 52-week range)
and merges any missing recent daily bars into the stored FactIQ series; the
five FX pairs refresh the same way. The full universe takes ~1 minute.

- Previous close is taken from the last completed bar strictly before the
  quote date (Yahoo's `chartPreviousClose` refers to the range start and is
  not used). Bars from a session still in progress are used for the live
  quote but never merged into the daily series.
- Refreshed files carry `refresh_source` / `refreshed_at` markers. A
  currency mismatch versus the stored payload aborts that name rather than
  mixing units.
- Nordic names refresh from the native OMX lines, which quote in the same
  SEK/EUR as the LSE order-book lines used for history; tiny line-to-line
  differences (~0.1–0.3%) are possible.
- FactIQ remains the source of record for fundamentals, statements, monthly
  history and deep price history. Suggested cadence: quotes daily (this
  script), monthly series monthly, statements quarterly (via FactIQ).

After refreshing, re-run `scripts/compute_metrics.py` and re-assemble the
dashboard; the "Data as of" banner picks up the newest quote date
automatically.

### 5c. Momentum engine & EWMA backtest (v2.5)

- History: 10-year canonical daily total-return series (191k sessions).
- EWMA: `ewm(span=N, adjust=False, min_periods=N)`; spans/pairs in
  config/momentum.yaml (single source for engine, backtest and UI).
- Crossover: fast>slow now AND fast<=slow on the previous VALID observation.
  Warm-up exits are not signals; days-above-slow are not new signals.
- Backtest: long-only, confirmation 1/3/5 sessions, next-CLOSE execution
  (no adjusted-open data — stated, slightly pessimistic), 25bps/side all-in,
  gross and net reported; chronological 60/40 in/out-of-sample split.
- 2026-07-13 finding, reported honestly: across 12 pairs x 3 confirmations,
  NO pair beat buy-and-hold out of sample 2022-26 (best excess -14.4%/yr) —
  timing cut max drawdown to -18.5% but this was a strong bull tape. Slow
  pairs (150/300, 100/300) dominate fast ones. Confirmed bullish crossovers
  were useful ENTRY markers: +21.1% mean 250-session forward TR, 71% positive
  (n=205). Momentum score = transparent config-weighted percentiles (0-100),
  components always visible. Universe = today's coverage: survivorship bias
  applies to all backtest figures. Rerun: scripts/backtest_momentum.py
  (also weekly via Actions); add a pair in config/momentum.yaml.

## 6. European close / post-close read-across

**The 16:30 UK benchmark (v2.8).** The benchmark is always defined as 16:30
in `Europe/London`; US session status uses `America/New_York` (both via
zoneinfo — never a fixed UTC offset, so UK/US DST-mismatch weeks are
handled). For each US peer the anchor is captured by the best available
method, in order of precedence, and stored in `market_benchmark_snapshots`
with its actual timestamp, source and quality — an exact 16:30 price is
never fabricated from an older observation:

1. `finnhub_candle` — completed 1-minute bar at 16:30 (needs paid
   entitlement; a 403 is detected once and the method skipped);
2. `finnhub_websocket` — last trade at/before 16:30 from a short capture
   window opened just before the benchmark;
3. `finnhub_quote` — REST quote taken around 16:30, dated by its own trade
   timestamp;
4. `yahoo_intraday_fallback` — the pre-existing 5-minute-bar mechanism.

Anchor quality (thresholds configurable in `config/finnhub.yaml`):
**exact** ≤ 60 s from target · **acceptable** ≤ 5 min · **stale** older ·
**unavailable** no valid price. A recovery run may upgrade an anchor but a
worse observation never overwrites a better one.
`move_since_1630_pct = (latest_us_price / anchor_price − 1) × 100`, shown
only where a usable anchor and a strictly later price both exist — closed
markets show "–", never 0.0%. European names still capture their own 16:30
snapshot into `eu_close_snapshots` (compatibility path retained).

**Provider precedence (v2.8).** Current US intraday quote: Finnhub → Yahoo
fallback → latest stored valid quote. 16:30 US benchmark: as the four
methods above. Historical daily prices: existing canonical pipeline
(unchanged). Fundamentals: FactIQ (unchanged). Momentum/EWMAs: internal
calculations on canonical prices (unchanged). Finnhub and Yahoo quotes are
cross-checked: prices observed within 60 s that differ > 1% raise a
`cross_source_price_conflict` warning; larger timestamp gaps are reported
as timestamp mismatches, not price conflicts.

**Catalyst methodology (v2.8).** For material movers (|move since 16:30 UK|
≥ 1%, plus the top 5 gainers/fallers), company-news *metadata* (headline,
source, link, summary — never article bodies) is fetched from Finnhub and
stored in `market_events`, deduplicated on provider event id (or a
deterministic URL hash). The displayed item is ranked transparently:
published after the benchmark, provider ties it to the ticker,
company-news category, recency. It is labelled **"Possible catalyst"** or
**"Latest company-specific update"** — the platform never asserts *"the
stock moved because…"*; with no relevant article it states "No recent
company-specific catalyst identified". No opaque AI-generated causality.

Peer-implied signals:

- Equal-weighted peer move = mean of peer 1-day moves.
- Correlation-weighted move = Σ(move × max(corr30,0)) / Σ max(corr30,0),
  correlations vs the (first) coverage security.
- Beta-adjusted move = mean over peers of (corr30 × σ_coverage/σ_peer × move).
- Outlier warning when the largest single peer move exceeds 3× |median| + 2pp.
- **Hit-rate backtesting of the peer-implied signal is not possible** with
  sampled daily history and no timestamped opens; the module is disabled and
  the limitation stated in-app.

## 7. Scenario engine

Mechanical, never price targets. Defaults per coverage name:
Bear = −10 % EBITDA at direct-peer Q1 multiple; Base = LTM EBITDA at current
multiple; Bull = +10 % EBITDA at peer Q3; plus rerating rows to peer median,
sector median and own 5-year median. For each:
`EV* = multiple × EBITDA*`, `Equity* = EV* − net debt − minority`,
`Price* = Equity*/diluted shares × FX(report→quote)`,
`Return = Price*/current − 1`, decomposed into earnings effect
(ΔEBITDA at constant multiple) and multiple effect (Δmultiple at new
EBITDA). Net-debt and share-count effects are zero in the defaults but
editable in the dashboard’s scenario page, which recomputes live in JS.

## 8. Sector-specific KPIs

FactIQ’s `sec_kpi` dataset covers US filers with >$10 bn market cap only;
none of the European coverage names have order/backlog/book-to-bill KPI
series, and mixing US-only KPIs into peer tables would bias comparisons.
The KPI module is therefore **disabled**, with this explanation shown.

## 9. Data-quality flags

Rendered on every row (screener `data_quality` column and drill-down):
unresolved lines, stale statements, fiscal-year-end differences (Siemens
Sep, Alstom Mar, Smiths Jul, GBX Aug, KMT/AMAT/KLAC Jun–Sep, OSK Dec since
FY2023), derived EBITDA/EBIT, reconstruction approximations, captive
finance, GBp/GBP units, ADR vs local share notes, corporate actions
(GE split, Crane split, Melrose demerger, Alstom-Bombardier, VISN
restructuring), and negative-earnings periods. Winsorisation is applied
only to chart axes (multiples clipped at the 2nd–98th percentile for
readability); underlying tables always carry raw values.

## 10. Known limitations (summary)

1. No consensus data → LTM basis everywhere; revisions/surprise/guidance
   modules disabled.
2. Intraday coverage is limited to the 16:30 UK benchmark layer (hybrid
   Finnhub/Yahoo, indicative data, licensing-gated pilot); everything else
   uses official closes.
3. Sampled price history → returns/correlations are approximations with
   n_obs shown.
4. Historical valuation series are annual and approximate (3–6 points).
5. Some US XBRL gaps are bridged with reconstructions (flagged per name).
6. Captive-finance names not comparable on consolidated EV multiples.
7. VISN and Crane carry structural data-quality warnings.
