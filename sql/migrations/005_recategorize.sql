-- Category cleanup (2026-10-17): Loan Payments (10) and Housing (8) are retired, and Bills &
-- Utilities (4) becomes Housing & Bills, the fairly fixed costs of living. The seeds carry the
-- mapping changes; this moves the hand-picked overrides to match. Run before the next dbt seed.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/005_recategorize.sql

BEGIN;

-- mortgage and the old VW car loan
UPDATE bronze.category_overrides SET category_id = 4 WHERE category_id = 10;

-- subscriptions go to Entertainment: Apple was overridden into Bills, and the CSV backfill's
-- Netflix and Prime rows map there through its "Bills & Utilities" label
UPDATE bronze.category_overrides o SET category_id = 7
FROM bronze.legacy_transactions t
WHERE t.external_transaction_id = o.transaction_id
  AND o.category_id = 4
  AND t.description ILIKE 'APPLE.COM/BILL%';

INSERT INTO bronze.category_overrides (transaction_id, category_id)
SELECT external_transaction_id, 7
FROM bronze.legacy_transactions
WHERE external_category = 'Bills & Utilities'
  AND (description ILIKE 'NETFLIX%' OR description ILIKE 'AMAZON PRIME*%')
ON CONFLICT (transaction_id) DO NOTHING;

-- fail loudly rather than leave an override pointing at a retired category
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM bronze.category_overrides WHERE category_id IN (8, 10)) THEN
        RAISE EXCEPTION 'overrides still point at a retired category';
    END IF;
END $$;

COMMIT;
