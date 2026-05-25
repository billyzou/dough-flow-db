-- ============================================================
-- Personal Finance Database Schema
-- PostgreSQL
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    account_id       SERIAL PRIMARY KEY,
    external_account_id VARCHAR(100) UNIQUE,
    name             VARCHAR(100) NOT NULL,
    type             VARCHAR(50)  NOT NULL CHECK (type IN ('checking', 'savings', 'credit', 'investment', 'cash')),
    institution      VARCHAR(100),
    currency         CHAR(3)      NOT NULL DEFAULT 'USD',
    balance          NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    category_id   SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL UNIQUE,
    parent_id     INT REFERENCES categories(category_id) ON DELETE SET NULL,
    type          VARCHAR(10)  NOT NULL CHECK (type IN ('income', 'expense')),
    color         CHAR(7),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS category_map (
    external_category VARCHAR(150) PRIMARY KEY,
    category_id       INT NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id           SERIAL PRIMARY KEY,
    account_id               INT          NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    category_id              INT          REFERENCES categories(category_id) ON DELETE SET NULL,
    external_transaction_id  VARCHAR(100) UNIQUE,
    external_category        VARCHAR(150),
    transaction_type         VARCHAR(30),
    amount                   NUMERIC(15, 2) NOT NULL,
    description              TEXT,
    merchant                 VARCHAR(150),
    status                   VARCHAR(10)  NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'pending')),
    transaction_date         DATE         NOT NULL,
    posted_date              DATE,
    is_recurring             BOOLEAN      NOT NULL DEFAULT FALSE,
    notes                    TEXT,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_id  ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_category_id ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date        ON transactions(transaction_date);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN 
    NEW.updated_at = NOW(); 
    RETURN NEW; 
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON accounts 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER trg_transactions_updated_at
    BEFORE UPDATE ON transactions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at();


CREATE TABLE IF NOT EXISTS account_balances (
    balance_id    SERIAL PRIMARY KEY,
    account_id    INT          NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    snapshot_date DATE         NOT NULL,
    currency      CHAR(3)      NOT NULL DEFAULT 'USD',
    balance       NUMERIC(15, 2) NOT NULL,
    UNIQUE (account_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
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
