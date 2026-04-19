# dough-flow-db

A local PostgreSQL database for tracking personal finances — accounts, transactions, budgets, and recurring rules.

## Purpose
This is a learning project for building DE skills (pipeline design, schema management, orchestration).
Prefer explicit, readable patterns over clever abstractions — the goal is understanding the plumbing,
not shipping production code. Avoid introducing orchestration tools (Airflow, Prefect, dbt) until
the core pipeline is working end-to-end.

## Goal
Build a personal finance pipeline that pulls real transaction data from bank accounts via Plaid,
stores it in a local PostgreSQL database, and enables querying/analysis of spending over time.
Near-term: get Plaid Sandbox working end-to-end (connect account, pull transactions, insert to DB).
Eventually: connect real accounts and automate syncing.

## Stack
- PostgreSQL 14+
- Python (ingestion scripts)
- SQL schema managed via `sql/schema.sql`
- Credentials via `.env` (never commit this)
- Running on WSL2 (Ubuntu)

## Database
- Name: `dough_flow_db`
- Connection via env vars: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
- PostgreSQL installed and running on WSL2; DB and user `bzou` created as owner

## Plaid Integration
- Plaid account created, Sandbox credentials obtained
- Required `.env` vars: PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV=sandbox
- Upsert strategy: insert on `transaction_id`, DO NOTHING on conflict (idempotent re-runs)
- Pending transactions: skip until posted (status = 'posted') to avoid ghost records

## Schema Decisions
- All primary keys named specifically (e.g. `account_id`, `transaction_id`) not generic `id`
- `plaid_account_id` on `accounts` — for mapping Plaid accounts to local accounts
- `plaid_transaction_id` on `transactions` — UNIQUE, enables idempotent upserts
- `plaid_category` on `transactions` — stores Plaid's raw category label alongside our own `category_id`
- `status` on `transactions` — `posted` or `pending`; skip pending on ingest
- Amount sign convention: negative = expense, positive = income (flip Plaid's sign on insert)
- `category_id` nullable — own category system to be built after seeing real transaction data

## Schema Tables
- `accounts` — bank accounts, credit cards, investment accounts
- `categories` — hierarchical income/expense categories (supports sub-categories)
- `transactions` — individual income and expense records
- `transfers` — money moved between accounts
- `budgets` — monthly or yearly spending limits per category
- `recurring_rules` — templates for recurring transactions (rent, subscriptions, etc.)

## Project Structure
- `sql/schema.sql` — table definitions, indexes, triggers
- `sql/seed.sql` — sample data for development
- `scripts/` — Python ingestion and sync scripts
- `.env.example` — env var template
- `.env` — local credentials (gitignored)

## Rules
- Never DROP or TRUNCATE tables without explicit confirmation
- Never commit `.env`
- All schema changes go in `sql/schema.sql`
- Always use transactions for multi-step writes
- Prefer explicit SQL over ORM magic — write raw psycopg2 or similar
- When generating ingestion code, include logging so pipeline steps are visible