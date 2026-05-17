# dough-flow-db

A local PostgreSQL database for tracking personal finances — accounts, transactions, budgets, and recurring rules.

## Purpose
This is a learning project for building DE skills (pipeline design, schema management, orchestration).
Prefer explicit, readable patterns over clever abstractions — the goal is understanding the plumbing,
not shipping production code.

## Goal
Build a personal finance pipeline that pulls real transaction data from bank accounts via Plaid,
stores it in a PostgreSQL database, and enables querying/analysis of spending over time.
All v1 banks enrolled (Wealthfront, Chase, Citi). Pipeline runs daily via Airflow on a home server.
Next: dbt transformations, BI dashboard.

## Stack
- PostgreSQL 14 (runs in Docker)
- Python (ingestion scripts)
- Airflow 2.9.1 (runs in Docker, schedules daily ingest)
- SQL schema managed via `sql/schema.sql`
- Credentials via `.env` (never commit this)
- Docker Compose stack deployed on home server (Windows 10 + WSL2)

## Database
- Name: `dough_flow_db`
- Connection via env vars: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
- Runs in Docker container `dough-flow-db-postgres-1`; exposed on port 5433
- Same container also hosts `airflow_meta` DB for Airflow internals
- User `bzou` is superuser; `airflow` user has access but is not owner

## Plaid Integration
- Provider: Plaid (switched back from Teller — Teller had weak security posture and no SOC2)
- Auth: `client_id` + environment-specific `secret` via API; no mTLS
- Required `.env` vars: PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, plus one PLAID_TOKEN_<BANK> per enrollment
- Pricing: Free trial (10 production connections)
- Enrolled (v1 complete): Wealthfront, Chase, Amex, Citi (Schwab/wife/mortgage deferred)
- Token flow: `plaid_create_link_token.py` → `plaid_link.html` (browser) → `plaid_exchange_public_token.py` → add to `.env`
- Upsert strategy: insert on `external_transaction_id`, DO NOTHING on conflict (idempotent re-runs)
- Pending transactions: skip until posted to avoid ghost records
- Pagination: implemented in `fetch_transactions()` (500 per page, loops until complete)
- Chase/Wealthfront use OAuth (no credential handover); Plaid is SOC2 Type II + ISO 27001
- Always invoke Python as `.venv/bin/python3` on local — system `python3` is NOT the venv (broken path pre-`src/` move)
- In Docker, `python3` is correct — packages are installed directly into the Airflow image via `requirements.txt`

## Schema Decisions
- All primary keys named specifically (e.g. `account_id`, `transaction_id`) not generic `id`
- `external_account_id` on `accounts` — provider-agnostic name for mapping external accounts to local accounts
- `external_transaction_id` on `transactions` — UNIQUE, enables idempotent upserts
- `external_category` on `transactions` — stores Plaid's PFC primary label (e.g. FOOD_AND_DRINK, TRANSPORTATION)
- `transaction_type` on `transactions` — Plaid's transaction_type field; informational
- `merchant` on `transactions` — populated from Plaid's `merchant_name`
- `status` on `transactions` — `posted` or `pending`; skip pending on ingest
- Amount sign convention: negative = expense, positive = income. Plaid normalizes sign across all account types (positive = money out), so we flip once on insert: `amount = -t['amount']`
- `category_id` nullable — mapped via `category_map` table from PFC labels; run `categorize.py` after ingest

## Schema Tables
- `accounts` — bank accounts, credit cards, investment accounts
- `categories` — hierarchical income/expense categories (supports sub-categories)
- `transactions` — individual income and expense records
- `transfers` — money moved between accounts
- `budgets` — monthly or yearly spending limits per category
- `recurring_rules` — templates for recurring transactions (rent, subscriptions, etc.)

## Project Structure
- `docker-compose.yml` — full stack: postgres, airflow-init, airflow-scheduler, airflow-webserver
- `Dockerfile` — extends `apache/airflow:2.9.1` with `requirements.txt`
- `dags/ingest_plaid.py` — Airflow DAG; runs daily at 10am UTC
- `sql/schema.sql` — table definitions, indexes, triggers
- `sql/categories_seed.sql` — category taxonomy + Plaid PFC→category mappings
- `sql/monthly_spending.sql`, `sql/category_trends.sql` — aggregation queries
- `scripts/ingest_plaid.py` — Plaid ingest (active); loops over PLAID_TOKEN_* env vars
- `scripts/categorize.py` — backfills `category_id` from `category_map`
- `scripts/plaid_create_link_token.py` — mints a link_token for Plaid Link (expires 30 min)
- `scripts/plaid_link.html` — browser UI to connect a bank via Plaid Link; outputs public_token
- `scripts/plaid_exchange_public_token.py` — exchanges public_token for permanent access_token
- `scripts/plaid_sandbox_token.py` — mints a sandbox access_token without a browser (dev/test only)
- `scripts/explore_plaid.ipynb` — sandbox exploration notebook
- `.env.example` — env var template
- `.env` — local credentials (gitignored)

## Rules
- Never DROP or TRUNCATE tables without explicit confirmation
- Never commit `.env`
- All schema changes go in `sql/schema.sql`
- Always use transactions for multi-step writes
- Prefer explicit SQL over ORM magic — write raw psycopg2 or similar
- When generating ingestion code, include logging so pipeline steps are visible