-- Bronze table for Yahoo Finance closing prices (scripts/backfill_prices.py).
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/004_security_prices.sql

BEGIN;

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

COMMIT;
