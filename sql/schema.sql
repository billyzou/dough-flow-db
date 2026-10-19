-- ============================================================
-- Personal Finance Database Schema (medallion)
-- PostgreSQL
--
-- bronze  raw data as it arrived, written by scripts/ (this file)
-- silver  cleaned facts and dims, built by dbt (dough_flow_db/models/silver)
-- gold    dashboard-ready aggregates, built by dbt (dough_flow_db/models/gold)
-- ops     pipeline metadata
--
-- Categories and the Plaid category map are dbt seeds (dough_flow_db/seeds), loaded into bronze.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS ops;

-- Every account we track. account_id is the key all layers join on.
-- Plaid-linked accounts are registered by ingest_plaid.py the first time they're seen;
-- hand-entered accounts (no Plaid link) are added by hand. type and institution are only
-- needed for hand-entered accounts: linked accounts take them from Plaid in silver.
CREATE TABLE IF NOT EXISTS bronze.accounts (
    account_id          SERIAL PRIMARY KEY,
    external_account_id VARCHAR(100) UNIQUE,
    name                VARCHAR(100) NOT NULL,
    type                VARCHAR(50)  CHECK (type IN ('checking', 'savings', 'credit', 'investment', 'cash')),
    institution         VARCHAR(100),
    currency            CHAR(3)      NOT NULL DEFAULT 'USD',
    owner               VARCHAR(20)  CHECK (owner IN ('husband', 'wife')),
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Plaid /transactions/get rows, untouched. A transaction gets a new row only when its
-- payload changes, so this is the full history of what Plaid told us.
CREATE TABLE IF NOT EXISTS bronze.plaid_transactions (
    plaid_transaction_id VARCHAR(100) NOT NULL,
    payload_hash         CHAR(32)     NOT NULL,
    enrollment           VARCHAR(150) NOT NULL,
    payload              JSONB        NOT NULL,
    loaded_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plaid_transaction_id, payload_hash)
);

-- Plaid account payloads (including balances), one row per account per ingest run.
CREATE TABLE IF NOT EXISTS bronze.plaid_accounts (
    load_id          BIGSERIAL    PRIMARY KEY,
    enrollment       VARCHAR(150) NOT NULL,
    institution_name VARCHAR(100),
    plaid_account_id VARCHAR(100) NOT NULL,
    payload          JSONB        NOT NULL,
    loaded_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Plaid /investments/holdings/get rows, one per holding per ingest run. Only for
-- enrollments with the investments product.
CREATE TABLE IF NOT EXISTS bronze.plaid_holdings (
    load_id          BIGSERIAL    PRIMARY KEY,
    enrollment       VARCHAR(150) NOT NULL,
    plaid_account_id VARCHAR(100) NOT NULL,
    security_id      VARCHAR(100) NOT NULL,
    payload          JSONB        NOT NULL,
    loaded_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- The securities those holdings (and investment transactions) point to, one row per
-- security per ingest run: close_price changes daily.
CREATE TABLE IF NOT EXISTS bronze.plaid_securities (
    load_id     BIGSERIAL    PRIMARY KEY,
    enrollment  VARCHAR(150) NOT NULL,
    security_id VARCHAR(100) NOT NULL,
    payload     JSONB        NOT NULL,
    loaded_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Plaid /investments/transactions/get rows (buys, sells, dividends, fees). Plaid only
-- goes back 24 months, so this keeps older trades. New row only when a payload changes.
CREATE TABLE IF NOT EXISTS bronze.plaid_investment_transactions (
    investment_transaction_id VARCHAR(100) NOT NULL,
    payload_hash              CHAR(32)     NOT NULL,
    enrollment                VARCHAR(150) NOT NULL,
    payload                   JSONB        NOT NULL,
    loaded_at                 TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (investment_transaction_id, payload_hash)
);

-- Daily closing prices from Yahoo Finance (scripts/backfill_prices.py). Split-adjusted but not
-- dividend-adjusted, so they multiply with today's share counts. Only used to rebuild holdings
-- history before the first Plaid snapshot. Re-fetching a day replaces it: a later split changes
-- every earlier close.
CREATE TABLE IF NOT EXISTS bronze.security_prices (
    ticker     VARCHAR(20)    NOT NULL,
    price_date DATE           NOT NULL,
    close      NUMERIC(18, 6) NOT NULL,
    loaded_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, price_date)
);

-- Hand-entered balance snapshots (scripts/update_balance.py). Append-only: re-entering a
-- date adds a row and silver keeps the latest.
CREATE TABLE IF NOT EXISTS bronze.manual_balances (
    account_id    INT            NOT NULL REFERENCES bronze.accounts(account_id) ON DELETE CASCADE,
    snapshot_date DATE           NOT NULL,
    balance       NUMERIC(15, 2) NOT NULL,
    entered_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Hand-picked categories that win over the category_map seed. transaction_id is the
-- source's id (Plaid transaction_id, or csv_<hash> for the CSV backfill).
CREATE TABLE IF NOT EXISTS bronze.category_overrides (
    transaction_id VARCHAR(100) PRIMARY KEY,
    category_id    INT          NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Frozen copies of the pre-medallion tables (2026-10-11). They're the only source for
-- the 2025 CSV backfill and for balances older than the Plaid payloads in bronze.
-- Nothing writes to them except scripts/delete_transactions.py.
CREATE TABLE IF NOT EXISTS bronze.legacy_transactions (
    transaction_id           INT            PRIMARY KEY,
    account_id               INT            NOT NULL,
    category_id              INT,
    external_transaction_id  VARCHAR(100)   UNIQUE,
    external_category        VARCHAR(150),
    transaction_type         VARCHAR(30),
    amount                   NUMERIC(15, 2) NOT NULL,
    description              TEXT,
    merchant                 VARCHAR(150),
    status                   VARCHAR(10)    NOT NULL,
    transaction_date         DATE           NOT NULL,
    posted_date              DATE,
    is_recurring             BOOLEAN        NOT NULL,
    notes                    TEXT,
    created_at               TIMESTAMPTZ    NOT NULL,
    updated_at               TIMESTAMPTZ    NOT NULL
);

CREATE TABLE IF NOT EXISTS bronze.legacy_account_balances (
    balance_id    INT            PRIMARY KEY,
    account_id    INT            NOT NULL,
    snapshot_date DATE           NOT NULL,
    currency      CHAR(3)        NOT NULL,
    balance       NUMERIC(15, 2) NOT NULL,
    UNIQUE (account_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id        SERIAL PRIMARY KEY,
    enrollment    VARCHAR(150),
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    success       BOOLEAN      NOT NULL,
    error_message TEXT,
    rows_seen     INT,
    rows_inserted INT,
    rows_skipped  INT
);

-- One row per Ask Dough Bot question (dashboard), for its "usually ~Xs" estimate. Timing only.
CREATE TABLE IF NOT EXISTS ops.ask_runs (
    run_id   SERIAL PRIMARY KEY,
    asked_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    seconds  NUMERIC(7, 1) NOT NULL,
    steps    INT          NOT NULL,
    success  BOOLEAN      NOT NULL
);
