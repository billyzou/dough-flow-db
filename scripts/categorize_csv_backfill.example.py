#!/usr/bin/env python3
"""
categorize_csv_backfill.example.py

Template for categorize_csv_backfill.py — the actual file is gitignored
because DESCRIPTION_PATTERNS contains merchant names that are personally
identifying (specific employers, local restaurants, utilities, etc.).

To set up: copy this file to categorize_csv_backfill.py and fill in
your own patterns.

Usage (one-time, after CSV import):
    .venv/bin/python3 scripts/categorize_csv_backfill.py
"""

import logging
import os

import psycopg2
from dotenv import load_dotenv

from categorize import build_db_conn, categorize

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Patterns matched with ILIKE against transaction description.
# Used for CSV-imported transactions that have no external_category.
# First match wins — put more specific patterns before broad ones.
# Format: (ilike_pattern, category_name)
DESCRIPTION_PATTERNS = [
    # Income — payroll and interest
    ('%PAYROLL%',               'Income'),
    ('%EDI PAYMNT%',            'Income'),   # direct deposit (ACH format)
    ('%EDI PYMT%',              'Income'),   # payroll variant ACH format
    ('%UI Deposit%',            'Income'),   # unemployment insurance
    ('INTEREST PAYMENT',        'Income'),
    ('% interest',              'Income'),   # monthly savings interest

    # Loan Payments
    ('%HOME MTG%',              'Loan Payments'),

    # Transfers — add your brokerage, credit card, and bank transfer patterns
    # ('%EDI PYMNTS%',          'Transfers'),   # brokerage transfer
    # ('%ACH PMT%',             'Transfers'),   # credit card payment
    # ('Online Transfer%',      'Transfers'),
    # ('Zelle payment%',        'Transfers'),

    # Bills & Utilities
    ('APPLE.COM/BILL%',         'Bills & Utilities'),
    ('IRS%USATAXPYMT%',         'Bills & Utilities'),
    ('%TAX COLL%',              'Bills & Utilities'),
    ('%UTIL%BILLPAY%',          'Bills & Utilities'),

    # Food — POS prefixes catch most restaurants generically
    ('TST*%',                   'Food'),     # Toast POS
    ('SQ *%',                   'Food'),     # Square POS (with space)
    ('SQ*%',                    'Food'),     # Square POS (no space)
    ('DD *%',                   'Food'),     # DoorDash
    ('CHIPOTLE%',               'Food'),
    ('STARBUCKS%',              'Food'),
    ('%MCDONALD%',              'Food'),
    # Add your local restaurants here:
    # ('MY FAVORITE RESTAURANT%', 'Food'),

    # Transport
    ('CHEVRON%',                'Transport'),
    ('%VALERO%',                'Transport'),
    ('%PARKING%',               'Transport'),

    # Personal Care
    ('CVS%PHARMACY%',           'Personal Care'),

    # Entertainment
    ('%PATREON%',               'Entertainment'),
]


def categorize_by_description(conn):
    """
    Second-pass categorization using ILIKE patterns on description.
    Only touches rows where category_id IS NULL.
    """
    update_sql = """
        UPDATE transactions t
        SET category_id = c.category_id
        FROM categories c
        WHERE c.name = %s
          AND t.description ILIKE %s
          AND t.category_id IS NULL
    """
    unmapped_sql = """
        SELECT external_category, COUNT(*) AS n
        FROM transactions
        WHERE category_id IS NULL
        GROUP BY external_category
        ORDER BY n DESC
    """

    total = 0
    with conn.cursor() as cur:
        for pattern, category_name in DESCRIPTION_PATTERNS:
            cur.execute(update_sql, (category_name, pattern))
            total += cur.rowcount

        log.info(f"Categorized {total} transactions by description pattern")

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
    log.info("=== Starting CSV backfill categorization ===")
    conn = build_db_conn()
    try:
        categorize(conn)
        categorize_by_description(conn)
    finally:
        conn.close()
    log.info("=== Backfill complete ===")


if __name__ == '__main__':
    main()
