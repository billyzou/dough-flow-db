# dough-flow-db

A self-hosted personal finance pipeline. Real bank transactions pulled daily from Plaid, stored in PostgreSQL, transformed with dbt, and visualized in Superset — all orchestrated by Airflow running on a home server.

Built as a hands-on DE learning project: the goal is understanding the plumbing, not shipping production code.

---

## Pipeline

```
Plaid API  (production, 4 banks enrolled)
    │
    ▼
scripts/ingest_plaid.py   ← Airflow triggers this daily at 10am UTC
    │  psycopg2 upsert on external_transaction_id
    ▼
PostgreSQL 14  (dough_flow_db)
    │
    ▼
dbt  (staging views → mart views)
    │
    ▼
Apache Superset  (self-hosted, spending dashboards)
```

Everything runs in Docker Compose on a home Ubuntu server.

---

## Stack

| Layer | Tool |
|---|---|
| Ingestion | Python + Plaid API |
| Orchestration | Apache Airflow 2.9.1 |
| Storage | PostgreSQL 14 |
| Transformation | dbt |
| Visualization | Apache Superset |
| Infrastructure | Docker Compose, home server (Ubuntu) |

---

## Schema

| Table | Description |
|---|---|
| `accounts` | Bank accounts, credit cards, investment accounts |
| `transactions` | Individual transactions; source of truth for all analysis |
| `account_balances` | Point-in-time balance snapshots per account |
| `categories` | Hierarchical income/expense taxonomy (supports sub-categories) |
| `category_map` | Maps Plaid's Personal Finance Category labels to local categories |
| `budgets` | Monthly or yearly spending limits per category |
| `transfers` | Money moved between own accounts |
| `pipeline_runs` | Observability: rows fetched/inserted/errors/runtime per DAG run |

---

## Key design decisions

**Idempotent upserts** — transactions insert on `external_transaction_id` with `DO NOTHING` on conflict. Re-running the DAG never creates duplicates.

**Skip pending transactions** — Plaid surfaces pending transactions before they post. Skipping them avoids ghost records that get amended or cancelled.

**ELT, not ETL** — ingest stores raw Plaid data (including `external_category`, `merchant`, `transaction_type`). Category mapping runs separately via `categorize.py` and dbt. Clean separation between extract and transform.

**Amount sign normalization at ingest** — Plaid uses positive = money out across all account types. We flip once on insert (`amount = -t['amount']`), so negative = expense and positive = income throughout the DB.

**Observability table** — every DAG run writes a row to `pipeline_runs` with row counts, error messages, and runtime. No external monitoring needed at this scale.

**Plaid over alternatives** — evaluated Teller (no SOC2, small company risk) and direct scraping. Plaid is SOC2 Type II + ISO 27001; Chase and Wealthfront use OAuth so no credentials are handed over.

**dbt views, not tables** — all dbt models materialize as views. The dataset is small (~1,700 transactions) so there's no performance argument for tables, and views stay current automatically.

---

## Project structure

```
├── dags/
│   ├── ingest_plaid.py       # Airflow DAG: daily ingest
│   └── dbt_run.py            # dbt run (manual)
├── dough_flow_db/            # dbt project
│   └── models/
│       ├── staging/          # stg_transactions (view)
│       └── marts/            # monthly_spending, category_trends, net_worth (views)
├── scripts/
│   ├── ingest_plaid.py       # Plaid → Postgres ingest
│   ├── categorize.py         # Backfills category_id from category_map
│   ├── plaid_create_link_token.py
│   ├── plaid_exchange_public_token.py
│   └── plaid_link.html       # Browser UI for Plaid Link enrollment
├── sql/
│   ├── schema.sql            # Table definitions, indexes, triggers
│   ├── categories_seed.sql   # Category taxonomy + Plaid PFC mappings
│   ├── monthly_spending.sql
│   └── category_trends.sql
├── docker-compose.yml        # Full stack: postgres, airflow, superset
├── Dockerfile                # Airflow image + requirements
├── Dockerfile.superset       # Superset image + psycopg2-binary
└── .env.example              # Required env vars (Plaid keys, DB creds)
```

---

## Enrolled banks

Wealthfront, Chase, Amex, Citi — all via Plaid production credentials. Fidelity 401k accounts added manually (Plaid blocks dev accounts for Fidelity; SnapTrade rejected on similar security grounds).
