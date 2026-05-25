#!/usr/bin/env python3
"""
update_balance.py

Manually insert or update an account balance snapshot for today.

Usage:
    .venv/bin/python3 scripts/update_balance.py "My Investment Account" 42000.00
    .venv/bin/python3 scripts/update_balance.py "My Investment Account" 42000.00 --date 2026-05-01
"""

import argparse
import logging
import os
from datetime import date

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def build_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def update_balance(conn, account_name, balance, snapshot_date):
    with conn.cursor() as cur:
        cur.execute("SELECT account_id FROM accounts WHERE name = %s", (account_name,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No account found with name: '{account_name}'")
        account_id = row[0]

        cur.execute("""
            INSERT INTO account_balances (account_id, snapshot_date, balance)
            VALUES (%s, %s, %s)
            ON CONFLICT (account_id, snapshot_date) DO UPDATE SET balance = EXCLUDED.balance
        """, (account_id, snapshot_date, balance))

    conn.commit()
    log.info(f"Set balance for '{account_name}' (id={account_id}) on {snapshot_date}: ${balance:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Manually update an account balance snapshot.")
    parser.add_argument("account_name", help="Exact account name as stored in the accounts table")
    parser.add_argument("balance", type=float, help="Balance amount in USD")
    parser.add_argument("--date", default=str(date.today()), help="Snapshot date (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()

    with build_db_conn() as conn:
        update_balance(conn, args.account_name, args.balance, args.date)


if __name__ == "__main__":
    main()
