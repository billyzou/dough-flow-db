-- Zelle payments are transfers, not income or spending (2026-10-24). Plaid already labels them
-- TRANSFER_IN / TRANSFER_OUT; the CSV backfill's rows (Jan 2025 - Jan 2026) were overridden into
-- other categories, mostly Income. This moves those overrides to Transfers. Run, then dbt run, so
-- gold picks it up.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/009_zelle_transfers.sql

BEGIN;

UPDATE bronze.category_overrides o SET category_id = 11
FROM bronze.legacy_transactions t
WHERE t.external_transaction_id = o.transaction_id
  AND o.category_id <> 11
  AND t.description ILIKE 'Zelle payment%';

-- fail loudly rather than leave one outside Transfers
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM bronze.category_overrides o
        JOIN bronze.legacy_transactions t ON t.external_transaction_id = o.transaction_id
        WHERE o.category_id <> 11 AND t.description ILIKE 'Zelle payment%'
    ) THEN
        RAISE EXCEPTION 'a Zelle payment is still overridden outside Transfers';
    END IF;
END $$;

COMMIT;
