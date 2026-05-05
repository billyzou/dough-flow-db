#!/usr/bin/env python3
"""
import_csv.py

Imports historical transactions from bank CSV exports into dough_flow_db.
Reads all CSVs from data/csv_import/, detects format by header, and upserts.

File naming convention: {account_id}_{institution}[_suffix].csv
Idempotent: uses a hash of (account_id, date, description, amount) as external_transaction_id.
"""

import csv
import hashlib
import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parents[1] / '.env')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

CSV_DIR = Path(__file__).parents[1] / 'data' / 'csv_import'
IMPORT_START_DATE = '2025-01-01'


def make_txn_id(account_id, date, description, amount):
    key = f"csv_{account_id}_{date}_{description}_{amount}"
    return "csv_" + hashlib.md5(key.encode()).hexdigest()


def parse_date(s):
    """Parse MM/DD/YYYY or M/D/YYYY to YYYY-MM-DD."""
    from datetime import datetime
    return datetime.strptime(s.strip(), '%m/%d/%Y').date()


def parse_chase_credit(path, account_id):
    """Transaction Date,Post Date,Description,Category,Type,Amount,Memo"""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            amount = float(row['Amount'])
            rows.append({
                'external_transaction_id': make_txn_id(account_id, row['Transaction Date'], row['Description'], amount),
                'account_id': account_id,
                'transaction_date': parse_date(row['Transaction Date']),
                'posted_date': parse_date(row['Post Date']),
                'description': row['Description'].strip(),
                'amount': amount,
                'external_category': row.get('Category') or None,
                'transaction_type': row.get('Type') or None,
                'merchant': None,
            })
    return rows


def parse_chase_bank(path, account_id):
    """Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #"""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            amount = float(row['Amount'])
            rows.append({
                'external_transaction_id': make_txn_id(account_id, row['Posting Date'], row['Description'], amount),
                'account_id': account_id,
                'transaction_date': parse_date(row['Posting Date']),
                'posted_date': parse_date(row['Posting Date']),
                'description': row['Description'].strip(),
                'amount': amount,
                'external_category': None,
                'transaction_type': row.get('Type') or None,
                'merchant': None,
            })
    return rows


def parse_citi(path, account_id):
    """Status,Date,Description,Debit,Credit,Member Name"""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            debit = float(row['Debit']) if row['Debit'].strip() else 0.0
            credit = float(row['Credit']) if row['Credit'].strip() else 0.0
            amount = credit - debit
            rows.append({
                'external_transaction_id': make_txn_id(account_id, row['Date'], row['Description'], amount),
                'account_id': account_id,
                'transaction_date': parse_date(row['Date']),
                'posted_date': parse_date(row['Date']),
                'description': row['Description'].strip(),
                'amount': amount,
                'external_category': None,
                'transaction_type': None,
                'merchant': None,
            })
    return rows


def parse_amex(path, account_id):
    """Date,Description,Card Member,Account #,Amount,...,Category"""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            amount = -float(row['Amount'])  # Amex: positive = expense
            rows.append({
                'external_transaction_id': make_txn_id(account_id, row['Date'], row['Description'], amount),
                'account_id': account_id,
                'transaction_date': parse_date(row['Date']),
                'posted_date': parse_date(row['Date']),
                'description': row['Description'].strip(),
                'amount': amount,
                'external_category': row.get('Category') or None,
                'transaction_type': None,
                'merchant': None,
            })
    return rows


def parse_wealthfront(path, account_id):
    """Transaction date,Description,Type,Amount"""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            amount = float(row['Amount'])
            rows.append({
                'external_transaction_id': make_txn_id(account_id, row['Transaction date'], row['Description'], amount),
                'account_id': account_id,
                'transaction_date': parse_date(row['Transaction date']),
                'posted_date': parse_date(row['Transaction date']),
                'description': row['Description'].strip(),
                'amount': amount,
                'external_category': None,
                'transaction_type': row.get('Type') or None,
                'merchant': None,
            })
    return rows


PARSERS = {
    'transaction date,post date,description,category,type,amount': parse_chase_credit,
    'details,posting date,description,amount,type,balance': parse_chase_bank,
    'status,date,description,debit,credit': parse_citi,
    'date,description,card member,account #,amount': parse_amex,
    'transaction date,description,type,amount': parse_wealthfront,
}


def detect_parser(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        header = next(csv.reader(f))
    key = ','.join(h.strip().lower() for h in header)
    for prefix, parser in PARSERS.items():
        if key.startswith(prefix):
            return parser
    return None


def upsert_transactions(conn, rows):
    sql = """
        INSERT INTO transactions (
            external_transaction_id, account_id, transaction_date, posted_date,
            description, amount, external_category, transaction_type, merchant, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'posted')
        ON CONFLICT (external_transaction_id) DO NOTHING
    """
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            if str(row['transaction_date']) < IMPORT_START_DATE:
                continue
            cur.execute(sql, (
                row['external_transaction_id'],
                row['account_id'],
                row['transaction_date'],
                row['posted_date'],
                row['description'],
                row['amount'],
                row['external_category'],
                row['transaction_type'],
                row['merchant'],
            ))
            inserted += cur.rowcount
    conn.commit()
    return inserted


def dedupe_csv_vs_plaid(conn):
    sql = """
        DELETE FROM transactions t
        USING (
            SELECT account_id, MIN(transaction_date) as earliest_plaid
            FROM transactions
            WHERE external_transaction_id NOT LIKE 'csv_%'
            GROUP BY account_id
        ) cutoffs
        WHERE t.account_id = cutoffs.account_id
          AND t.external_transaction_id LIKE 'csv_%'
          AND t.transaction_date >= cutoffs.earliest_plaid
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        deleted = cur.rowcount
    conn.commit()
    return deleted


def backfill_account_balances(conn):
    """Backfill account_balances from Chase bank CSVs (accounts 41, 42) which have a Balance column."""
    BALANCE_ACCOUNTS = {41: '41_chase.CSV', 42: '42_chase.CSV'}
    total = 0
    sql = """
        INSERT INTO account_balances (account_id, snapshot_date, currency, balance)
        VALUES (%s, %s, 'USD', %s)
        ON CONFLICT (account_id, snapshot_date) DO UPDATE SET balance = EXCLUDED.balance
    """
    for account_id, filename in BALANCE_ACCOUNTS.items():
        path = CSV_DIR / filename
        if not path.exists():
            log.warning(f"Balance backfill: {filename} not found, skipping account {account_id}")
            continue

        seen_dates = set()
        snapshots = []
        with open(path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                balance_str = row.get('Balance', '').strip()
                if not balance_str:
                    continue
                txn_date = parse_date(row['Posting Date'])
                if str(txn_date) < IMPORT_START_DATE:
                    continue
                if txn_date not in seen_dates:
                    seen_dates.add(txn_date)
                    snapshots.append((account_id, txn_date, float(balance_str)))

        with conn.cursor() as cur:
            cur.executemany(sql, snapshots)
            inserted = cur.rowcount
        conn.commit()
        total += inserted
        log.info(f"account_balances backfill for account {account_id}: {inserted} snapshots inserted")

    return total


def main():
    conn = psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )

    total_inserted = 0
    try:
        for path in sorted(CSV_DIR.glob('*.[Cc][Ss][Vv]')):
            account_id = int(path.stem.split('_')[0])
            parser = detect_parser(path)
            if parser is None:
                log.warning(f"Unknown format, skipping: {path.name}")
                continue

            rows = parser(path, account_id)
            inserted = upsert_transactions(conn, rows)
            total_inserted += inserted
            log.info(f"{path.name}: {len(rows)} rows parsed, {inserted} inserted")

        deleted = dedupe_csv_vs_plaid(conn)
        log.info(f"Deduped {deleted} CSV rows overlapping with Plaid data")

        backfill_account_balances(conn)
    finally:
        conn.close()

    log.info(f"=== Done: {total_inserted} total rows inserted ===")


if __name__ == '__main__':
    main()
