-- Copy/paste this, replace merchant name:
-- docker exec -i dough-flow-db-postgres-1 psql -U $DB_USER -d dough_flow_db -v merchant='Some Merchant' -f - < sql/delete_transaction.sql

BEGIN;

SELECT transaction_id, transaction_date, merchant, description, amount
FROM transactions
WHERE merchant ILIKE :'merchant';

DELETE FROM transactions
WHERE merchant ILIKE :'merchant';

-- ROLLBACK;
COMMIT;
