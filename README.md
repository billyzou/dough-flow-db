<p align="center">
  <img src="dashboard/assets/icon.svg" alt="dough-flow-db icon" width="160">
</p>

# dough-flow-db

A self-hosted personal finance pipeline. Real bank transactions pulled daily from Plaid, stored in PostgreSQL, transformed with dbt, and visualized in a Streamlit dashboard — all orchestrated by Airflow running on a home server.

Built as a hands-on DE learning project: the goal is understanding the plumbing, not shipping production code.

---

## High-level pipeline

```
Plaid API  (production, 7 logins across 6 institutions)
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

Everything runs in Docker Compose (OrbStack) on a Mac mini home server.

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
                    │  Net Worth     balances by account and type      │
                    │  This Month    pace vs usual, top merchants      │
                    │  This Year     YTD, monthly spend, cash flow     │
                    │  Transactions  searchable list                   │
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
| Infrastructure | Docker Compose (OrbStack), Mac mini home server |

---

## Schema

Medallion layers, one Postgres schema each. `sql/schema.sql` defines bronze and ops; dbt builds the rest.

| Schema | Contents |
|---|---|
| `bronze` | Raw data as it arrived: Plaid transaction, account, holdings, security and investment transaction payloads (JSON), hand-entered balances, the account registry, category overrides, the category seeds, and frozen copies of the pre-medallion tables (the only source for the 2025 CSV backfill) |
| `silver` | `stg_*` cleaning views, then `fct_transactions` (one row per posted transaction), `fct_account_balances` (one row per account per snapshot day), `fct_holdings` (one row per account per security per snapshot day), `fct_holdings_reconstructed` (rebuilt history before the first snapshot; see [Investments](#investments)), `dim_account`, `dim_category`, `dim_security` |
| `gold` | Dashboard-ready models: `transactions` (facts joined to dims) and the aggregates built on it, plus `holdings` (positions with unrealized gain) and `holdings_history` (value and cost basis per holding per day; see [Investments](#investments)) |
| `ops` | `pipeline_runs`: rows fetched/inserted/errors/runtime per enrollment per run |

---

## Key design decisions

- **Raw, append-only bronze** — ingest stores each Plaid payload untouched, keyed on (transaction id, payload hash). Re-running the DAG adds nothing unless Plaid changed a transaction, and every rule below can be replayed over history.
- **All cleaning in dbt** — the sign flip (Plaid: positive = money out; ours: negative = expense), dropping pending transactions, Plaid's later corrections winning, and categorization (`category_overrides`, then `category_map`) all live in silver.
- **Legacy as a source** — the CSV files behind the 2025 backfill are gone, so the pre-medallion tables were frozen into `bronze.legacy_*`. Silver uses them only where Plaid has nothing.
- **Observability table** — every DAG run writes a row to `pipeline_runs` with row counts, error messages, and runtime. No external monitoring needed at this scale.
- **Plaid over alternatives** — evaluated Teller (no SOC2, small company risk) and direct scraping. Plaid is SOC2 Type II + ISO 27001; Chase and Wealthfront use OAuth so no credentials are handed over.
- **Display names live in the account registry** — `bronze.accounts.name` is set from Plaid the first time an account is seen and never overwritten, so renaming a row there renames the account everywhere. Owners are set there too.
- **Silver tables, gold views** — silver facts and dims are rebuilt by each dbt run; gold views stay cheap at this size. `update_balance.py` rebuilds the balance models itself so hand-entered balances show right away.

---

## Dashboard

Six tabs: **Net Worth**, **Holdings**, **This Month**, **This Year**, **Transactions** and **Notes**. Holdings covers accounts linked to Plaid with the investments product; add it to an existing link with `scripts/plaid_create_link_token.py <LABEL>`. Category names, column headers and chart titles have hover tooltips explaining what they include. On line charts, click a line or its label to show only that line (Option-click hides it, double-click resets). On Monthly Spend by Category, an isolated category also shows its prior year dashed, and clicking off the lines shows every category for that month as bars.

---

## Investments

The **Investments** tab breaks investment accounts down into holdings (ticker, value, cost basis, unrealized gain) and charts each holding's value against its cost basis over time.

**Where the data comes from**

| Data | Source | Lands in | Modeled as |
|---|---|---|---|
| Holdings and securities, daily | Plaid `/investments/holdings/get`, in the daily ingest | `bronze.plaid_holdings`, `bronze.plaid_securities` | `silver.fct_holdings`, `silver.dim_security` |
| Trades (buys, sells, dividends), up to 24 months back | Plaid `/investments/transactions/get`, in the daily ingest | `bronze.plaid_investment_transactions` | `silver.stg_plaid__investment_transactions` (not charted yet) |
| Tax lots (each purchase of the shares held now) | Part of each holding's payload | `bronze.plaid_holdings` | `silver.stg_plaid__tax_lots` |
| Daily closing prices of held tickers, plus the SPY benchmark | Yahoo Finance, `scripts/backfill_prices.py` (run by hand) | `bronze.security_prices` | `silver.stg_yahoo__prices`, `gold.security_prices` |

**Observed vs. reconstructed history.** Plaid only reports what is held *today*, so history is kept in two separate models:

- `silver.fct_holdings`: **observed**. One row per holding per day, exactly as Plaid reported it. Builds up one day per ingest from the first snapshot on.
- `silver.fct_holdings_reconstructed`: **rebuilt**, for the days before a holding's first snapshot. Like Plaid's morning snapshots, each row is the start of a day: shares held = the tax lots bought before it, cost basis = what those lots cost, value = shares x the previous trading day's close. The lots are taken from the first snapshot, so later sales don't change the rebuilt past.

`gold.holdings_history` unions the two with a `source` column (`snapshot` or `reconstructed`), so anything downstream can tell them apart.

**Checking it.** Plaid's daily account balances go back further than holdings, so summing the rebuilt holdings per account and comparing with them tests the reconstruction. An account that rarely sells matches within a fraction of a percent each day. A robo-advised account that sells to rebalance or harvest losses reads low in the past, by the value of shares it has since sold.

**Limits of the reconstruction**

- The lots only cover shares held now. Shares sold earlier are missing from both value and cost, so past value is understated for anything that was trimmed.
- A holding is only reconstructed when its lots are complete: every lot dated, and their shares match the first snapshot's. Lots can lag the snapshot by a few days of trades, so trades from the 0-3 days before it are allowed to make up the difference. Others start at the first snapshot.
- Cash held in an account has no history, so it isn't reconstructed.
- Funds with no public ticker (e.g. 401K target-date funds) have no Yahoo prices, and institutions often report no cost basis for them.
- Prices are split-adjusted, not dividend-adjusted, so they multiply with today's (post-split) share counts. Reinvested dividends show up as their own lots.

**Performance headline.** For the selected holding and period, the dollar gain is against what was paid (value minus starting value and money added; a holding that appears mid-period arrives at market value unless it's a first purchase). The % is a time-weighted price return: each day's market move, with shares added or sold valued at that day's price, chained. Deposits, their timing and purchase discounts don't move it; reinvested dividends count as deposits.

**Rolling 1-year return.** Its own section with its own period: on the left, the same time-weighted price return over the trailing year, as of each day, for the holdings picked in the Performance filters; on the right, up to four chosen tickers' price returns. Both against the S&P 500 (SPY's price return, at the previous close like the snapshots). The S&P line is a benchmark; history before the first snapshot only covers shares held now, so the older part flatters the holdings a little.

**Cost basis** is Plaid's `cost_basis`. When an institution leaves it blank but sends complete tax lots, their total is used instead (`stg_plaid__holdings`).

**Adding an account**

1. Give an existing Plaid link the investments product: `python3 scripts/plaid_create_link_token.py <LABEL>` (update mode, keeps the access token), or start a new link with a label that has no token yet. Open `scripts/plaid_link.html` and connect.
2. The next daily ingest lands its holdings. Then run `scripts/backfill_prices.py` and a full `dbt run` to rebuild its history.

Re-run `backfill_prices.py` after a stock split too: split-adjusted closes change for every earlier day. Always run dbt in full after changing holdings models: rebuilding a silver table drops the gold views built on it.

---

## Project structure

```
├── dashboard/
│   ├── app.py                # Streamlit dashboard (reads gold live)
│   └── assets/               # Logo, browser tab icon
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

Six institutions (seven logins) enrolled via Plaid production credentials: a mix of checking, savings, credit, brokerage and retirement accounts. A few accounts Plaid can't reach (e.g. crypto) are entered by hand each month with `scripts/update_balance.py`.
