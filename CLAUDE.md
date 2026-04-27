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

## Teller Integration
- Provider: Teller (switched from Plaid; pricing was unpublished and free tier was 200 API calls per product, not 200 Items as initially assumed)
- Auth: mTLS client certificate (cert + private key) plus per-enrollment access tokens
- Required `.env` vars: TELLER_CERT_PATH, TELLER_KEY_PATH, TELLER_SANDBOX_ACCESS_TOKEN (per-enrollment tokens added later for real banks)
- Cert/key stored in gitignored `.secrets/teller/`; private key chmod 600
- Pricing tier: Personal ($10/mo, up to 5 enrollments)
- Planned enrollments (v1): Chase, Wealthfront, Amex, Citi (Schwab/wife/mortgage deferred)
- Upsert strategy: insert on `external_transaction_id`, DO NOTHING on conflict (idempotent re-runs)
- Pending transactions: skip until posted (status = 'posted') to avoid ghost records
- No pagination yet — sandbox returns everything in one call; revisit when real banks bite

## Schema Decisions
- All primary keys named specifically (e.g. `account_id`, `transaction_id`) not generic `id`
- `external_account_id` on `accounts` — provider-agnostic name for mapping external accounts to local accounts
- `external_transaction_id` on `transactions` — UNIQUE, enables idempotent upserts
- `external_category` on `transactions` — stores the provider's raw category label alongside our own `category_id`
- `transaction_type` on `transactions` — Teller's transaction type (`card_payment`, `ach`, `deposit`, etc.); informational
- `merchant` on `transactions` — populated from Teller's `details.counterparty.name`
- `status` on `transactions` — `posted` or `pending`; skip pending on ingest
- Amount sign convention: negative = expense, positive = income — applied uniformly across account types. Teller stores from the account's perspective (credit-card charge is positive, bank withdrawal is negative), so credit-account amounts are flipped on insert; depository amounts are stored as-is
- `category_id` nullable — own category system; `service` (Teller's vaguest category) is intentionally unmapped until real merchant data clarifies how to bucket it

## Schema Tables
- `accounts` — bank accounts, credit cards, investment accounts
- `categories` — hierarchical income/expense categories (supports sub-categories)
- `transactions` — individual income and expense records
- `transfers` — money moved between accounts
- `budgets` — monthly or yearly spending limits per category
- `recurring_rules` — templates for recurring transactions (rent, subscriptions, etc.)

## Project Structure
- `sql/schema.sql` — table definitions, indexes, triggers
- `sql/categories_seed.sql` — category taxonomy + Teller→category mappings
- `sql/monthly_spending.sql`, `sql/category_trends.sql` — aggregation queries
- `scripts/ingest_teller.py` — Teller ingest (active)
- `scripts/categorize.py` — backfills `category_id` from `category_map`
- `scripts/explore_teller.ipynb` — sandbox exploration notebook
- `scripts/ingest_plaid.py`, `scripts/explore_plaid.ipynb` — legacy Plaid artifacts (do not run)
- `.env.example` — env var template
- `.env` — local credentials (gitignored)

## Rules
- Never DROP or TRUNCATE tables without explicit confirmation
- Never commit `.env`
- All schema changes go in `sql/schema.sql`
- Always use transactions for multi-step writes
- Prefer explicit SQL over ORM magic — write raw psycopg2 or similar
- When generating ingestion code, include logging so pipeline steps are visible