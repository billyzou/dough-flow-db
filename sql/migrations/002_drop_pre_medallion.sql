-- Drop the pre-medallion layout once this branch is live (after 001 and a dbt run).
-- Its data lives on in bronze.legacy_* and ops.pipeline_runs; categories are dbt seeds.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/002_drop_pre_medallion.sql

BEGIN;

DROP VIEW IF EXISTS
    public.category_comparison, public.category_trends, public.daily_balances,
    public.daily_cumulative_mtd, public.daily_cumulative_ytd, public.monthly_cash_flow,
    public.monthly_spending, public.mtd_avg_reference, public.net_worth,
    public.top_merchants, public.stg_transactions;

DROP TABLE IF EXISTS
    public.transactions, public.account_balances, public.category_map,
    public.categories, public.accounts, public.pipeline_runs;

DROP FUNCTION IF EXISTS public.update_updated_at();

-- Copies of every old table and view output, taken 2026-10-11 for validation
DROP SCHEMA IF EXISTS validation_baseline CASCADE;

COMMIT;
