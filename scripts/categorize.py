#!/usr/bin/env python3
"""
categorize.py

Assigns category_id to any transactions that don't have one yet,
using the category_map lookup table.

Run after ingest_teller.py.
Safe to re-run — only touches rows where category_id IS NULL.
"""

import logging
import os

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


def categorize(conn):
    """
    Update transactions.category_id by joining on category_map.
    Only touches rows where category_id IS NULL.
    """
    update_sql = """
        UPDATE transactions t
        SET category_id = m.category_id
        FROM category_map m
        WHERE t.external_category = m.external_category
          AND t.category_id IS NULL
    """
    unmapped_sql = """
        SELECT external_category, COUNT(*) AS n
        FROM transactions
        WHERE category_id IS NULL
        GROUP BY external_category
        ORDER BY n DESC
    """

    with conn.cursor() as cur:
        cur.execute(update_sql)
        updated = cur.rowcount
        log.info(f"Categorized {updated} transactions")

        cur.execute(unmapped_sql)
        unmapped = cur.fetchall()
        if unmapped:
            log.warning(f"{sum(n for _, n in unmapped)} transactions remain uncategorized:")
            for ext_cat, n in unmapped:
                log.warning(f"  {ext_cat or '(NULL)'}: {n}")
        else:
            log.info("All transactions are categorized")

    conn.commit()


def main():
    log.info("=== Starting categorization ===")
    conn = build_db_conn()
    try:
        categorize(conn)
    finally:
        conn.close()
    log.info("=== Categorization complete ===")


if __name__ == '__main__':
    main()
