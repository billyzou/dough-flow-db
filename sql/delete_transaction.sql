-- Copy/paste this, replace merchant name, then rerun dbt (or wait for the daily run):
-- docker exec -i dough-flow-db-postgres-1 psql -U $DB_USER -d dough_flow_db -v merchant='Some Merchant' -f - < sql/delete_transaction.sql

BEGIN;

SELECT plaid_transaction_id, payload->>'date', payload->>'merchant_name', payload->>'name', payload->>'amount'
FROM bronze.plaid_transactions
WHERE payload->>'merchant_name' ILIKE :'merchant';

SELECT external_transaction_id, transaction_date, merchant, description, amount
FROM bronze.legacy_transactions
WHERE merchant ILIKE :'merchant';

DELETE FROM bronze.plaid_transactions
WHERE payload->>'merchant_name' ILIKE :'merchant';

DELETE FROM bronze.legacy_transactions
WHERE merchant ILIKE :'merchant';

-- ROLLBACK;
COMMIT;
