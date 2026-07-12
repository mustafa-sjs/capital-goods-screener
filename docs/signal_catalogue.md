# Signal catalogue — what the data can actually support

Every signal assessed against: rationale, required data, current
availability, update frequency, failure modes, point-in-time testability.
Priorities: **NOW** (feasible today, implemented or config-only),
**MEDIUM** (needs accumulation or a normalisation layer), **LOW**,
**NOT FEASIBLE** (missing source — never faked).

## A. Relative valuation dislocation — NOW (implemented)
Peer/sector/history premiums, percentiles, z-scores — all live in the
screener with LTM basis. 1M/3M/6M *changes in* peer discount become
available as daily `feat_screener` snapshots accumulate (2–3 months of
history needed). Failure mode: cheap-for-a-reason names — pair with family E/F.

## B. Sector rerating/derating — NOW (implemented)
Median/quartile multiples by year + dispersion; rerating laggards preset.
Contribution split (earnings vs multiple) on the Scenarios page. Annual
history is coarse (3–6 obs) — treat percentile extremes with caution.

## C. Valuation × price momentum — NOW (implemented, upgraded 2026-07-13)
EWMA engine on canonical TR series: pairs 10/30, 20/60, 50/200; explicit
momentum states; 12-1 momentum; peer-relative 21D/63D. Status: descriptive.
Four-quadrant classification (cheap/rich × improving/weakening) using 1/3/6/
12M relative returns vs curated baskets + 52w drawdown. Momentum is context,
never auto-bullish/bearish. Testable once snapshots accumulate.

## D. Valuation × earnings revisions — **NOT FEASIBLE now**
No consensus feed exists in the pipeline (FactIQ carries none). The module
is disabled with an in-app notice; `raw_estimate_snapshots` is schema-ready
so the day a free consensus source appears, revisions/breadth/surprise
signals switch on without redesign. Reported-results momentum (rev growth,
margin change) is the labelled substitute — weaker but honest.

## E. Fundamental inflection — NOW (partial), MEDIUM (full)
Margin change, revenue growth, FCF conversion, leverage: implemented from
reported statements. Orders/backlog/book-to-bill: **not available** (FactIQ
KPI dataset lacks these for the European names) — flagged, not proxied.
Full time-series inflection detection needs the normalised-financials layer
(Phase 4).

## F. Quality-adjusted valuation — MEDIUM
Peer-relative comparisons (growth/margin/leverage vs basket) are live in the
drill-down. Regression residuals (expected multiple from fundamentals) need
the normalised layer + care with 4–7-name baskets — run at sector level
(79 names), never per-basket. Do not ship unstable small-sample models.

## G. Peer read-across — NOW (implemented, improving)
Eq/median/corr-weighted/beta-adjusted basket moves live. True 16:30 UK
snapshots (intraday workflow) upgrade this from full-session approximation
to genuine post-EU-close read-across. Historical directional accuracy /
hit-rate: testable after ~2 months of snapshots — roadmap, not claimed.

## H. Relative-value pairs — MEDIUM
Ingredients live (spreads, correlations with n_obs, fundamentals deltas).
A pairs page ranking |spread z| × correlation × fundamental-comparability is
config-only work once spread history accumulates from daily snapshots.

## I. Event/catalyst overlays — LOW / partially NOT FEASIBLE
No reliable free structured feed for earnings dates/investor days in the
pipeline. FactIQ earnings-call search (claims/pressure points) exists for US
names and can annotate drill-downs in a Claude session; automated calendars
would require scraping of uncertain reliability — deferred rather than faked.

## Point-in-time testing roadmap (Phase 4 — not yet claimed)
Daily `feat_screener` + `daily_change_events` + `eu_close_snapshots` are the
accumulating point-in-time record. After ≥3 months: forward 1/3/6M returns
vs peers by classification and preset; hit rates; IC; turnover; long/short
asymmetry; read-across accuracy around earnings vs quiet periods. **No
predictive power is claimed before this testing exists.**
