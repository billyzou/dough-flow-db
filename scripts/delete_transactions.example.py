#!/usr/bin/env python3
"""
delete_transactions.example.py

Template for deleting transactions by merchant name.
Copy to delete_transactions.py (gitignored) and add your merchant list.

Usage:
    .venv/bin/python3 scripts/delete_transactions.py
"""

import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

MERCHANTS_TO_DELETE = [
    m.strip()
    for m in os.environ.get('MERCHANTS_TO_DELETE', '').split(',')
    if m.strip()
]


def build_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def delete_merchants(conn, merchants):
    preview_sql = """
        SELECT transaction_id, transaction_date, merchant, amount
        FROM transactions
        WHERE merchant ILIKE ANY(%s)
        ORDER BY merchant, transaction_date
    """
    delete_sql = """
        DELETE FROM transactions
        WHERE merchant ILIKE ANY(%s)
    """
    patterns = [m for m in merchants]

    with conn.cursor() as cur:
        cur.execute(preview_sql, (patterns,))
        rows = cur.fetchall()
        if not rows:
            log.info("No matching transactions found.")
            return

        log.info(f"Rows to delete ({len(rows)}):")
        for row in rows:
            log.info(f"  {row}")

        cur.execute(delete_sql, (patterns,))
        log.info(f"Deleted {cur.rowcount} transactions")

    conn.commit()


def main():
    log.info("=== Starting delete ===")
    conn = build_db_conn()
    try:
        delete_merchants(conn, MERCHANTS_TO_DELETE)
    finally:
        conn.close()
    log.info("=== Done ===")


if __name__ == '__main__':
    main()
