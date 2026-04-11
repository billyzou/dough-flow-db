# dough-flow-db

A local PostgreSQL database for tracking personal finances — accounts, transactions, budgets, and recurring rules.

---

## Database Schema

| Table | Description |
|---|---|
| `accounts` | Bank accounts, credit cards, investment accounts, etc. |
| `categories` | Hierarchical income/expense categories (supports sub-categories) |
| `transactions` | Individual income and expense records |
| `transfers` | Money moved between accounts |
| `budgets` | Monthly or yearly spending limits per category |
| `recurring_rules` | Templates for recurring transactions (rent, subscriptions, etc.) |

---

## Setup

### Prerequisites

- PostgreSQL 14+ installed and running locally
- `psql` available in your terminal

### 1. Create the database

```bash
psql -U postgres -c "CREATE DATABASE finance_db;"
```

### 2. Configure your environment

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials
```

### 3. Apply the schema

```bash
psql -U your_user -d finance_db -f sql/schema.sql
```

### 4. (Optional) Load sample data

```bash
psql -U your_user -d finance_db -f sql/seed.sql
```

---

## Project Structure

```
.
├── sql/
│   ├── schema.sql    # Table definitions, indexes, triggers
│   └── seed.sql      # Sample data for development
├── .env.example      # Environment variable template
├── .gitignore
└── README.md
```
