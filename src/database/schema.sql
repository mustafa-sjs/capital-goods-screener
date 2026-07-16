-- Capital Goods research platform — persistent schema.
-- Portable SQL: runs on DuckDB (local dev) and Supabase Postgres (production).
-- Primary keys use the stable internal security KEY (TEXT) — these are
-- internal identifiers decoupled from tickers; ticker/exchange changes only
-- ever touch attribute columns, never keys.

-- ============================= reference =============================
CREATE TABLE IF NOT EXISTS securities (
    key            TEXT PRIMARY KEY,      -- stable internal id (e.g. 'ABBN')
    name           TEXT NOT NULL,
    ticker         TEXT,                  -- display ticker, may change
    exchange       TEXT,
    mic_code       TEXT,
    quote_ccy      TEXT NOT NULL,
    report_ccy     TEXT NOT NULL,
    yahoo_symbol   TEXT,                  -- retrieval id for price adapter
    factiq_symbol  TEXT,                  -- retrieval id for FactIQ
    active         BOOLEAN DEFAULT TRUE,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS coverage_groups (
    group_id   TEXT PRIMARY KEY,          -- slug of display name
    pack       TEXT NOT NULL,             -- e.g. 'capital_goods'
    subgroup   TEXT NOT NULL,
    display    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage_members (
    group_id   TEXT NOT NULL,
    key        TEXT NOT NULL,
    role       TEXT NOT NULL,             -- 'coverage' | 'peer'
    position   INTEGER,
    PRIMARY KEY (group_id, key, role)
);

CREATE TABLE IF NOT EXISTS data_sources (
    source     TEXT PRIMARY KEY,
    kind       TEXT,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS metric_definitions (
    metric     TEXT PRIMARY KEY,
    definition TEXT,
    basis      TEXT,                       -- 'LTM reported fallback' etc.
    version    TEXT
);

-- ============================ raw market =============================
CREATE TABLE IF NOT EXISTS raw_daily_prices (
    key          TEXT NOT NULL,
    price_date   DATE NOT NULL,
    open         DOUBLE PRECISION,
    high         DOUBLE PRECISION,
    low          DOUBLE PRECISION,
    close        DOUBLE PRECISION,
    volume       BIGINT,
    currency     TEXT,
    source       TEXT NOT NULL,           -- 'factiq' | 'yahoo' | 'manual_csv'
    ingested_at  TIMESTAMP,
    quality      TEXT DEFAULT 'ok',       -- 'ok' | 'flagged' | 'quarantined'
    PRIMARY KEY (key, price_date, source)
);

CREATE TABLE IF NOT EXISTS raw_monthly_prices (
    key          TEXT NOT NULL,
    price_date   DATE NOT NULL,
    close        DOUBLE PRECISION,
    currency     TEXT,
    source       TEXT NOT NULL,
    PRIMARY KEY (key, price_date, source)
);

CREATE TABLE IF NOT EXISTS raw_quotes (
    key          TEXT PRIMARY KEY,
    quote_date   DATE,
    close        DOUBLE PRECISION,
    prev_close   DOUBLE PRECISION,
    high_52w     DOUBLE PRECISION,
    low_52w      DOUBLE PRECISION,
    currency     TEXT,
    source       TEXT,
    refreshed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_fx_rates (
    pair         TEXT NOT NULL,           -- 'SEKUSD'
    rate_date    DATE NOT NULL,
    close        DOUBLE PRECISION,
    source       TEXT NOT NULL,
    PRIMARY KEY (pair, rate_date, source)
);

CREATE TABLE IF NOT EXISTS eu_close_snapshots (
    key             TEXT NOT NULL,
    obs_date        DATE NOT NULL,
    benchmark_time  TEXT NOT NULL,        -- '16:30 Europe/London'
    price           DOUBLE PRECISION,
    price_ts        TIMESTAMP,
    later_price     DOUBLE PRECISION,     -- e.g. subsequent US close
    later_ts        TIMESTAMP,
    currency        TEXT,
    source          TEXT,
    quality         TEXT DEFAULT 'ok',
    PRIMARY KEY (key, obs_date, benchmark_time)
);

-- Generalised intraday benchmark (v2.8): successor to eu_close_snapshots for
-- the US read-across. One row per security/session/benchmark carrying the
-- 16:30 UK anchor AND the latest observed price, each with source + quality.
-- eu_close_snapshots is retained as the compatibility read path for the
-- European capture until this table is validated (see CHANGELOG v2.8).
-- All TIMESTAMP columns store UTC.
CREATE TABLE IF NOT EXISTS market_benchmark_snapshots (
    key                     TEXT NOT NULL,
    observation_date        DATE NOT NULL,        -- US session date
    benchmark_name          TEXT NOT NULL,        -- 'european_close_1630_uk'
    target_ts               TIMESTAMP,            -- 16:30 Europe/London in UTC
    anchor_price            DOUBLE PRECISION,
    anchor_ts               TIMESTAMP,
    latest_price            DOUBLE PRECISION,
    latest_ts               TIMESTAMP,
    currency                TEXT,
    anchor_source           TEXT,                 -- finnhub_candle | finnhub_websocket |
                                                  -- finnhub_quote | yahoo_intraday_fallback | manual
    latest_source           TEXT,
    anchor_quality          TEXT,                 -- exact | acceptable | stale | unavailable
    observation_age_seconds INTEGER,              -- target minus anchor observation
    run_id                  TEXT,
    updated_at              TIMESTAMP,
    PRIMARY KEY (key, observation_date, benchmark_name)
);

-- Periodic US intraday quote observations (audit trail of updates — a few
-- rows per name per session, never a tick store).
CREATE TABLE IF NOT EXISTS intraday_quote_snapshots (
    key            TEXT NOT NULL,
    quote_ts       TIMESTAMP NOT NULL,            -- provider's own quote time (UTC)
    price          DOUBLE PRECISION,
    previous_close DOUBLE PRECISION,
    currency       TEXT,
    source         TEXT NOT NULL,
    quality        TEXT DEFAULT 'ok',
    run_id         TEXT,
    ingested_at    TIMESTAMP,
    PRIMARY KEY (key, quote_ts, source)
);

-- Company-specific news / catalyst metadata (headline + link only, never
-- article bodies). Unique on provider + provider event id; when the provider
-- returns no reliable id the ingester substitutes a deterministic URL hash.
CREATE TABLE IF NOT EXISTS market_events (
    provider          TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    key               TEXT,
    symbol            TEXT,
    published_at      TIMESTAMP,
    headline          TEXT,
    summary           TEXT,
    source_name       TEXT,
    article_url       TEXT,
    category          TEXT,
    related_symbol    TEXT,
    retrieved_at      TIMESTAMP,
    event_date        DATE,
    after_1630_uk     BOOLEAN,
    relevance_score   DOUBLE PRECISION,
    PRIMARY KEY (provider, provider_event_id)
);

-- Events calendar (v2.9): provider-sourced rows only (Finnhub earnings for
-- US peers). Curated coverage dates + rule-based macro events come straight
-- from config/events_calendar.yaml at render time and are never stored.
CREATE TABLE IF NOT EXISTS calendar_events (
    event_date  DATE NOT NULL,
    event_type  TEXT NOT NULL,             -- 'results' | 'macro' | 'fed' | 'company'
    subject     TEXT NOT NULL,             -- security key or macro slug
    title       TEXT,
    source      TEXT,                      -- 'finnhub' | 'curated' | 'rule'
    confirmed   BOOLEAN DEFAULT TRUE,
    details     TEXT,                      -- e.g. 'before open', EPS estimate
    updated_at  TIMESTAMP,
    PRIMARY KEY (event_date, event_type, subject)
);

CREATE TABLE IF NOT EXISTS canonical_prices (
    key          TEXT NOT NULL,
    session_date DATE NOT NULL,
    close_raw    DOUBLE PRECISION,
    close_split  DOUBLE PRECISION,
    close_tr     DOUBLE PRECISION,
    volume       BIGINT,
    currency     TEXT,
    exchange_tz  TEXT,
    source       TEXT NOT NULL,
    complete     BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (key, session_date, source)
);

CREATE TABLE IF NOT EXISTS price_reconciliation (
    key          TEXT NOT NULL,
    session_date DATE NOT NULL,
    stored       DOUBLE PRECISION,
    fetched      DOUBLE PRECISION,
    diff_pct     DOUBLE PRECISION,
    run_id       TEXT,
    status       TEXT DEFAULT 'open',
    PRIMARY KEY (key, session_date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    key          TEXT NOT NULL,
    action_date  DATE NOT NULL,
    kind         TEXT NOT NULL,
    value        DOUBLE PRECISION,
    currency     TEXT,
    PRIMARY KEY (key, action_date, kind)
);

-- ========================= raw fundamentals ==========================
-- Raw payloads as received (FactIQ market-data / SEC XBRL extracts).
CREATE TABLE IF NOT EXISTS raw_fundamentals (
    key         TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- 'isa','isq','bsa','bsq','cfa','sec_*'
    payload     TEXT NOT NULL,            -- JSON as text (portable)
    fetched_at  TIMESTAMP,
    PRIMARY KEY (key, kind)
);

CREATE TABLE IF NOT EXISTS filing_dates (
    key         TEXT NOT NULL,
    period_end  DATE NOT NULL,
    filed_date  DATE NOT NULL,
    lag_days    INTEGER,
    source      TEXT DEFAULT 'factiq_sec',
    PRIMARY KEY (key, period_end)
);

-- Point-in-time estimate snapshots. FactIQ currently exposes NO consensus
-- data, so this table stays empty by design; it exists so revisions become
-- computable the day a consensus source is added, without a schema change.
CREATE TABLE IF NOT EXISTS raw_estimate_snapshots (
    key           TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    metric        TEXT NOT NULL,          -- 'ntm_ebitda', 'fy1_eps', ...
    period        TEXT NOT NULL,
    value         DOUBLE PRECISION,
    source        TEXT NOT NULL,
    PRIMARY KEY (key, snapshot_date, metric, period, source)
);

-- ========================= derived features ==========================
-- Loaded from the validated engine output each refresh; snapshot_date keyed
-- so history accumulates and screens are point-in-time auditable.
CREATE TABLE IF NOT EXISTS feat_screener (
    snapshot_date TEXT NOT NULL,
    key           TEXT NOT NULL,
    payload       TEXT NOT NULL,          -- full screener row JSON
    classification TEXT,
    prem_disc_vs_peers_pct DOUBLE PRECISION,
    prem_disc_vs_sector_pct DOUBLE PRECISION,
    ev_ebitda_ltm DOUBLE PRECISION,
    PRIMARY KEY (snapshot_date, key)
);

CREATE TABLE IF NOT EXISTS feat_close_rows (
    snapshot_date TEXT NOT NULL,
    key           TEXT NOT NULL,
    coverage_group TEXT NOT NULL,
    payload       TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, key, coverage_group)
);

CREATE TABLE IF NOT EXISTS feat_close_groups (
    snapshot_date TEXT NOT NULL,
    group_display TEXT NOT NULL,
    payload       TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, group_display)
);

CREATE TABLE IF NOT EXISTS feat_scenarios (
    snapshot_date TEXT NOT NULL,
    key           TEXT NOT NULL,
    scenario      TEXT NOT NULL,
    payload       TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, key, scenario)
);

CREATE TABLE IF NOT EXISTS feat_valuation_history (
    key       TEXT NOT NULL,
    year      INTEGER NOT NULL,
    ev_ebitda DOUBLE PRECISION,
    PRIMARY KEY (key, year)
);

CREATE TABLE IF NOT EXISTS app_payload (
    snapshot_date TEXT PRIMARY KEY,
    payload       TEXT NOT NULL           -- full dashboard_data.json
);

CREATE TABLE IF NOT EXISTS momentum_backtest_results (
    run_date TEXT NOT NULL,
    fast INTEGER NOT NULL,
    slow INTEGER NOT NULL,
    confirm_days INTEGER NOT NULL,
    test_window TEXT NOT NULL,
    ann_return_pct DOUBLE PRECISION, excess_ann_pct DOUBLE PRECISION,
    sharpe DOUBLE PRECISION, sortino DOUBLE PRECISION,
    max_drawdown_pct DOUBLE PRECISION, n_trades INTEGER,
    win_rate_pct DOUBLE PRECISION, turnover_ann DOUBLE PRECISION,
    time_invested_pct DOUBLE PRECISION, stability DOUBLE PRECISION,
    score DOUBLE PRECISION, cost_bps INTEGER,
    PRIMARY KEY (run_date, fast, slow, confirm_days, test_window)
);

-- ============================ application ============================
CREATE TABLE IF NOT EXISTS watchlists (
    watchlist_id TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT DEFAULT 'custom',   -- longs/shorts/holdings/earnings/research/custom
    created_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist_members (
    watchlist_id TEXT NOT NULL,
    key          TEXT NOT NULL,
    note         TEXT,
    priority     TEXT,
    thesis_status TEXT,
    added_at     TIMESTAMP,
    reviewed_at  TIMESTAMP,
    PRIMARY KEY (watchlist_id, key)
);

CREATE TABLE IF NOT EXISTS saved_screens (
    screen_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    definition TEXT NOT NULL,             -- JSON filter spec
    created_at TIMESTAMP
);

-- ============================ operational ============================
CREATE TABLE IF NOT EXISTS refresh_runs (
    run_id        TEXT PRIMARY KEY,
    mode          TEXT NOT NULL,
    started_at    TIMESTAMP,
    finished_at   TIMESTAMP,
    status        TEXT,                   -- 'success' | 'partial' | 'failed'
    rows_inserted INTEGER DEFAULT 0,
    rows_updated  INTEGER DEFAULT 0,
    items_failed  INTEGER DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS refresh_run_items (
    run_id   TEXT NOT NULL,
    item     TEXT NOT NULL,
    status   TEXT NOT NULL,
    message  TEXT,
    PRIMARY KEY (run_id, item)
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_id    TEXT NOT NULL,
    check_name TEXT NOT NULL,
    severity  TEXT NOT NULL,              -- info | warning | error | critical
    subject   TEXT NOT NULL,
    message   TEXT,
    created_at TIMESTAMP,
    PRIMARY KEY (run_id, check_name, subject)
);

CREATE TABLE IF NOT EXISTS daily_change_events (
    snapshot_date TEXT NOT NULL,
    key           TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    detail        TEXT,
    PRIMARY KEY (snapshot_date, key, event_type)
);

CREATE TABLE IF NOT EXISTS free_tier_usage (
    as_of   TIMESTAMP NOT NULL,
    metric  TEXT NOT NULL,
    value   DOUBLE PRECISION,
    detail  TEXT,
    PRIMARY KEY (as_of, metric)
);
