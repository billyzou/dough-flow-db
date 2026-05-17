-- Copy/paste this, replace merchant name:
-- cd /home/billy/dough-flow-db (on server: ssh billy@192.168.2.117 first)
-- docker exec -i dough-flow-db-postgres-1 psql -U bzou -d dough_flow_db -v merchant='Some Merchant' -f - < sql/delete_transaction.sql

BEGIN;

SELECT transaction_id, transaction_date, merchant, description, amount
FROM transactions
WHERE merchant ILIKE :'merchant';

DELETE FROM transactions
WHERE merchant ILIKE :'merchant';

-- ROLLBACK;
COMMIT;
