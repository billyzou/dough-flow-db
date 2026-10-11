-- One-time move from the flat public tables to bronze (2026-10-11). Run after schema.sql.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/001_medallion.sql

BEGIN;

INSERT INTO bronze.accounts (account_id, external_account_id, name, type, institution, currency, owner, is_active, created_at)
SELECT account_id, external_account_id, name, type, institution, currency, owner, is_active, created_at
FROM public.accounts;
SELECT setval('bronze.accounts_account_id_seq', (SELECT max(account_id) FROM bronze.accounts));

INSERT INTO bronze.legacy_transactions SELECT * FROM public.transactions;
INSERT INTO bronze.legacy_account_balances SELECT * FROM public.account_balances;

-- categorize.py only filled empty categories, so these kept whatever they were first given:
-- the CSV backfill's description rules, hand edits, and mappings since changed in category_map.
INSERT INTO bronze.category_overrides (transaction_id, category_id)
SELECT t.external_transaction_id, t.category_id
FROM public.transactions t
LEFT JOIN public.category_map m USING (external_category)
WHERE t.category_id IS DISTINCT FROM m.category_id;

INSERT INTO ops.pipeline_runs SELECT * FROM public.pipeline_runs;
SELECT setval('ops.pipeline_runs_run_id_seq', (SELECT max(run_id) FROM ops.pipeline_runs));

COMMIT;
