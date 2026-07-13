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
