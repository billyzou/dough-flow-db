-- Copy/paste this, replace values for txn_id and merchant:
-- cd /home/billy/dough-flow-db
-- docker exec -i dough-flow-db-postgres-1 psql -U bzou -d dough_flow_db -v txn_id=123 -v merchant='Some Merchant' -f - < sql/delete_transaction.sql

BEGIN;

SELECT transaction_id, transaction_date, merchant, description, amount
FROM transactions
WHERE transaction_id = :'txn_id'
  AND merchant ILIKE :'merchant';

DELETE FROM transactions
WHERE transaction_id = :'txn_id'
  AND merchant ILIKE :'merchant';

-- ROLLBACK;
COMMIT;
