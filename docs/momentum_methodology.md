# Momentum methodology

## Research grounding (primary sources)

- **Jegadeesh & Titman (1993)**, "Returns to Buying Winners and Selling
  Losers", *Journal of Finance* 48(1): cross-sectional momentum — 3–12 month
  formation/holding periods earn significant excess returns; motivates our
  63D/126D/252D horizons and peer-relative ranking rather than absolute-only.
- **Fama & French momentum factor construction**: prior (2–12) return —
  skip the most recent month to avoid short-term reversal. Implemented as
  `mom_12_1`: total return from 252 to 21 sessions ago.
- **Moskowitz, Ooi & Pedersen (2012)**, "Time Series Momentum", *JFE* 104(2):
  an instrument's own past 12-month excess return predicts its future return;
  motivates the absolute-momentum block alongside cross-sectional measures.
- **pandas.DataFrame.ewm documentation**: with `adjust=False` the EMA is the
  standard recursive filter y_t = (1−α)y_{t−1} + αx_t, α = 2/(span+1).
  We set `min_periods = span` so no value is emitted before a full window.
- **Harvey, Liu & Zhu (2016)**, "...and the Cross-Section of Expected
  Returns": with hundreds of tested factors, t-stat hurdles must rise;
  we therefore ship momentum states as **descriptive** until point-in-time
  validation exists, and will not tune EMA windows on the evaluation sample.

## Implementation choices

- Basis: **total-return** canonical series (dividends/specials reinvested);
  raw prices never drive momentum (see docs/price_data_audit.md, VISN case).
- Backtested EMA crossover set (user-selected 2026-07-17, in
  `config/momentum.yaml`): 5/30, 10/40, 10/60, 20/60, 20/100, 20/120,
  40/150, 50/200 sessions; `adjust=False`; `min_periods = span`; missing
  sessions are absent rows on the security's own exchange calendar (no
  forward-fill across halts). The descriptive state block additionally uses
  the fixed 10/30, 20/60, 50/200 trio (state rules key off 20/60).
- Derived per pair: gap %, 5-session gap slope, gap acceleration, crossover
  date & sessions-since, gap percentile & z-score vs own 5y distribution.
- States (rules in `src/features/momentum.py` docstring, 20/60 pair):
  emerging positive inflection · established uptrend · fading uptrend ·
  emerging breakdown · established downtrend · indeterminate.
- Confirmation fields: 63D TR return, 21D/63D peer-relative deltas
  (equal-weighted and median), trend strength (% of pairs bullish),
  % of horizons positive. Volume confirmation deferred (volume quality
  uneven across lines).
- Risk block: EW volatility (span 20/60, annualised √252), 52w drawdown,
  max drawdown over the stored history (peak-to-trough on the total-return
  series; verified against independent recomputation 2026-07-17).

## Backtest aggregation & reporting (v2.8.2)

- Portfolio = equal weight across names **trading that day** (closed-market
  days are excluded from the day's mean, not zero-filled — zero-filling
  damped portfolio vol/drawdown; fixed 2026-07-17).
- Every result window reports the strategy AND its buy-and-hold benchmark
  over the *identical* dates, including `bench_max_drawdown_pct`, so
  drawdown reduction is always shown against context. The OOS benchmark
  starts after the warm-up tail, same as the strategy.
- Portfolio drawdowns are diversified-basket numbers and are labelled as
  such in the UI; per-share strategy evidence (all configured pairs ×
  confirmations, full window) is published as `security_pairs` /
  `security_best` in `momentum_backtest.json` and surfaced on Stock
  Screener → Price Trend ("Selected company") and Company Analysis →
  Price Trend (best-for-this-company preselection).
- 2026-07-17 run: universe winner 50/200, confirm 5 (OOS Sharpe 1.31);
  **no configured pair beat buy-and-hold out of sample** (excess −14 to
  −20%/yr in a strongly rising 2024–26 window) — trend settings mainly
  reduced drawdowns. Stated on-page; crossovers remain research prompts.

## Validation status & anti-overfitting stance

Every momentum output is labelled **"descriptive — not backtested"**. The
current universe is today's coverage (survivorship bias: delistings and
past coverage changes are absent). Backtesting requirements before any
predictive language: walk-forward splits, parameter-stability across the
three pairs, rank IC and quantile spreads vs direct peers, turnover and
cost haircuts, regime splits, and multiple-testing discounts per Harvey
et al. Windows will not be optimised and evaluated on the same sample.
