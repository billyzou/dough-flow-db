-- Bronze tables for Plaid investments (holdings, securities, investment transactions).
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/003_plaid_investments.sql

BEGIN;

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

COMMIT;
