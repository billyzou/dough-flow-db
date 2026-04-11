-- ============================================================
-- Personal Finance Database Schema
-- PostgreSQL
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    type          VARCHAR(50)  NOT NULL CHECK (type IN ('checking', 'savings', 'credit', 'investment', 'cash')),
    institution   VARCHAR(100),
    currency      CHAR(3)      NOT NULL DEFAULT 'USD',
    balance       NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL UNIQUE,
    parent_id     INT REFERENCES categories(id) ON DELETE SET NULL,
    type          VARCHAR(10)  NOT NULL CHECK (type IN ('income', 'expense')),
    color         CHAR(7),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id            SERIAL PRIMARY KEY,
    account_id    INT          NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    category_id   INT          REFERENCES categories(id) ON DELETE SET NULL,
    amount        NUMERIC(15, 2) NOT NULL,
    description   TEXT,
    merchant      VARCHAR(150),
    transaction_date DATE      NOT NULL,
    posted_date   DATE,
    is_recurring  BOOLEAN      NOT NULL DEFAULT FALSE,
    notes         TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transfers (
    id                  SERIAL PRIMARY KEY,
    from_account_id     INT NOT NULL REFERENCES accounts(id),
    to_account_id       INT NOT NULL REFERENCES accounts(id),
    amount              NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
    transfer_date       DATE NOT NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_different_accounts CHECK (from_account_id <> to_account_id)
);

CREATE TABLE IF NOT EXISTS budgets (
    id            SERIAL PRIMARY KEY,
    category_id   INT          NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    amount        NUMERIC(15, 2) NOT NULL CHECK (amount >= 0),
    period        VARCHAR(10)  NOT NULL CHECK (period IN ('monthly', 'yearly')),
    start_date    DATE         NOT NULL,
    end_date      DATE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recurring_rules (
    id            SERIAL PRIMARY KEY,
    account_id    INT          NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    category_id   INT          REFERENCES categories(id) ON DELETE SET NULL,
    amount        NUMERIC(15, 2) NOT NULL,
    description   TEXT,
    merchant      VARCHAR(150),
    frequency     VARCHAR(20)  NOT NULL CHECK (frequency IN ('daily', 'weekly', 'biweekly', 'monthly', 'yearly')),
    next_due_date DATE         NOT NULL,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_id  ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_category_id ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date        ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_budgets_category_id      ON budgets(category_id);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE OR REPLACE TRIGGER trg_transactions_updated_at
    BEFORE UPDATE ON transactions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE OR REPLACE TRIGGER trg_budgets_updated_at
    BEFORE UPDATE ON budgets FOR EACH ROW EXECUTE FUNCTION update_updated_at();
