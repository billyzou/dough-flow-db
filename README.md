<p align="center">
  <img src="dashboard/assets/icon.svg" alt="dough-flow-db icon" width="160">
</p>

# dough-flow-db

A self-hosted personal finance pipeline. Real bank transactions pulled daily from Plaid, stored in PostgreSQL, transformed with dbt, and visualized in a Streamlit dashboard — all orchestrated by Airflow running on a home server.

Built as a hands-on DE learning project: the goal is understanding the plumbing, not shipping production code.

---

## High-level pipeline

```
Plaid API  (production, 4 banks enrolled)
    │
    ▼
scripts/ingest_plaid.py   ← Airflow triggers this daily at 10am UTC
    │  raw JSON payloads, append-only
    ▼
PostgreSQL 14  (dough_flow_db)
    │
    ▼
dbt  (bronze → silver facts/dims → gold aggregates)
    │
    ▼
Streamlit  (self-hosted, spending dashboard)
```

Everything runs in Docker Compose on a home Ubuntu server.

---

## Detailed pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  SOURCES                                                            │
│                                                                     │
│  Bank API (Plaid) ───────────────────────────────┐                  │
│  CSV backfill ───────────────────────────────────┤                  │
│  Manual entry (investment balances) ─────────────┤                  │
└──────────────────────────────────────────────────┼──────────────────┘
                                                   │
                    ┌──────────────────────────────▼──────────────────┐
                    │  INGESTION  (Airflow · daily 10am UTC)           │
                    │                                                  │
                    │  ingest_plaid.py                                 │
                    │  · raw Plaid JSON, new row only if it changed    │
                    │  · audit log → ops.pipeline_runs                 │
                    │  delete_transactions.py                          │
                    │  · purges private transactions from bronze       │
                    └──────────────────────────────┬──────────────────┘
                                                   │
                    ┌──────────────────────────────▼──────────────────┐
                    │  BRONZE  (raw, as it arrived)                    │
                    │                                                  │
                    │  plaid_transactions   plaid_accounts             │
                    │  manual_balances      accounts (registry)        │
                    │  category_overrides   categories, category_map   │
                    │  legacy_transactions  legacy_account_balances    │
                    └──────────────────────────────┬──────────────────┘
                                                   │
                    ┌──────────────────────────────▼──────────────────┐
                    │  SILVER  (dbt tables · cleaned and conformed)    │
                    │                                                  │
                    │  stg_*  one view per bronze source               │
                    │  fct_transactions      fct_account_balances      │
                    │  dim_account           dim_category              │
                    └──────────────────────────────┬──────────────────┘
                                                   │
                    ┌──────────────────────────────▼──────────────────┐
                    │  GOLD  (dbt views · dashboard-ready)             │
                    │                                                  │
                    │  transactions, monthly_spending, category_trends │
                    │  daily_balances, net_worth, ...                  │
                    └──────────────────────────────┬──────────────────┘
                                                   │
                    ┌──────────────────────────────▼──────────────────┐
                    │  SERVING  (Streamlit · dashboard/app.py)         │
                    │                                                  │
                    │  YTD / MTD cumulative spend                      │
                    │  spend by category (YTD, MTD)                    │
                    │  monthly trend by category                       │
                    │  net cash flow                                   │
                    │  top merchants                                   │
                    └─────────────────────────────────────────────────┘
```

---

## Stack

| Layer | Tool |
|---|---|
| Ingestion | Python + Plaid API |
| Orchestration | Apache Airflow 2.9.1 |
| Storage | PostgreSQL 14 |
| Transformation | dbt |
| Visualization | Streamlit |
| Infrastructure | Docker Compose, home server (Ubuntu) |

---

## Schema

Medallion layers, one Postgres schema each. `sql/schema.sql` defines bronze and ops; dbt builds the rest.

| Schema | Contents |
|---|---|
| `bronze` | Raw data as it arrived: Plaid transaction and account payloads (JSON), hand-entered balances, the account registry, category overrides, the category seeds, and frozen copies of the pre-medallion tables (the only source for the 2025 CSV backfill) |
| `silver` | `stg_*` cleaning views, then `fct_transactions` (one row per posted transaction), `fct_account_balances` (one row per account per snapshot day), `dim_account`, `dim_category` |
| `gold` | Dashboard-ready models: `transactions` (facts joined to dims) and the aggregates built on it |
| `ops` | `pipeline_runs`: rows fetched/inserted/errors/runtime per enrollment per run |

---

## Key design decisions

- **Raw, append-only bronze** — ingest stores each Plaid payload untouched, keyed on (transaction id, payload hash). Re-running the DAG adds nothing unless Plaid changed a transaction, and every rule below can be replayed over history.
- **All cleaning in dbt** — the sign flip (Plaid: positive = money out; ours: negative = expense), dropping pending transactions, Plaid's later corrections winning, and categorization (`category_overrides`, then `category_map`) all live in silver.
- **Legacy as a source** — the CSV files behind the 2025 backfill are gone, so the pre-medallion tables were frozen into `bronze.legacy_*`. Silver uses them only where Plaid has nothing.
- **Observability table** — every DAG run writes a row to `pipeline_runs` with row counts, error messages, and runtime. No external monitoring needed at this scale.
- **Plaid over alternatives** — evaluated Teller (no SOC2, small company risk) and direct scraping. Plaid is SOC2 Type II + ISO 27001; Chase and Wealthfront use OAuth so no credentials are handed over.
- **Silver tables, gold views** — silver facts and dims are rebuilt by each dbt run; gold views stay cheap at this size. `update_balance.py` rebuilds the balance models itself so hand-entered balances show right away.

---

## Project structure

```
├── dashboard/
│   └── app.py                # Streamlit dashboard (reads gold live)
├── dags/
│   ├── ingest_plaid.py       # Airflow DAG: daily ingest
│   └── dbt_run.py            # dbt seed + run, after the ingest DAG
├── dough_flow_db/            # dbt project
│   ├── seeds/                # categories, category_map (→ bronze)
│   └── models/
│       ├── staging/          # stg_* views over bronze (→ silver)
│       ├── silver/           # facts and dims (tables)
│       └── gold/             # dashboard models (views)
├── scripts/
│   ├── ingest_plaid.py       # Plaid → bronze ingest
│   ├── update_balance.py     # Hand-entered balances → bronze
│   ├── plaid_create_link_token.py
│   ├── plaid_exchange_public_token.py
│   └── plaid_link.html       # Browser UI for Plaid Link enrollment
├── sql/
│   ├── schema.sql            # bronze and ops tables
│   └── migrations/           # One-time moves between layouts
├── docker-compose.yml        # Full stack: postgres, airflow, streamlit
├── Dockerfile                # Airflow image + requirements
├── Dockerfile.streamlit      # Streamlit image + psycopg2-binary
└── .env.example              # Required env vars (Plaid keys, DB creds)
```

---

## Enrolled institutions

Four institutions enrolled via Plaid production credentials (mix of checking, credit, and investment accounts). One investment account provider added manually — Plaid blocks dev-tier access for that institution; alternatives evaluated and rejected on security grounds.
