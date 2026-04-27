#!/usr/bin/env python3
"""
ingest_teller.py

Pulls accounts and transactions from Teller and upserts them into Postgres.
Categorization is a separate step — run scripts/categorize.py after this.

Sign convention (matches CLAUDE.md): negative = expense, positive = income.
Teller stores from the account's perspective, so credit card amounts are
flipped on insert; depository amounts are stored as-is.
"""

import logging
import os
from decimal import Decimal

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
CERT  = os.path.join(REPO_ROOT, os.environ['TELLER_CERT_PATH'])
KEY   = os.path.join(REPO_ROOT, os.environ['TELLER_KEY_PATH'])
TOKEN = os.environ['TELLER_SANDBOX_ACCESS_TOKEN']
BASE  = 'https://api.teller.io'

# Teller (type, subtype) -> our accounts.type enum.
ACCOUNT_TYPE_MAP = {
    ('depository', 'checking'):    'checking',
    ('depository', 'savings'):     'savings',
    ('credit',     'credit_card'): 'credit',
}


def teller_get(path):
    r = requests.get(f'{BASE}{path}', cert=(CERT, KEY), auth=(TOKEN, ''))
    r.raise_for_status()
    return r.json()


def build_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def upsert_accounts(conn, teller_accounts):
    """Upsert accounts; return {external_account_id: (account_id, type)} for the transaction step."""
    sql = """
        INSERT INTO accounts (external_account_id, name, type, institution, currency, balance)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (external_account_id) DO UPDATE SET
            name        = EXCLUDED.name,
            type        = EXCLUDED.type,
            institution = EXCLUDED.institution,
            currency    = EXCLUDED.currency,
            balance     = EXCLUDED.balance
        RETURNING account_id, external_account_id, type
    """
    lookup = {}
    with conn.cursor() as cur:
        for a in teller_accounts:
            local_type = ACCOUNT_TYPE_MAP.get((a['type'], a['subtype']))
            if local_type is None:
                log.warning(f"Skipping account {a['id']}: unmapped type/subtype {a['type']}/{a['subtype']}")
                continue

            balance = teller_get(f"/accounts/{a['id']}/balances").get('ledger')

            cur.execute(sql, (
                a['id'],
                a['name'],
                local_type,
                a['institution']['name'],
                a['currency'],
                Decimal(balance) if balance is not None else Decimal('0'),
            ))
            account_id, ext_id, typ = cur.fetchone()
            lookup[ext_id] = (account_id, typ)
            log.info(f"Upserted account {a['name']} (local id={account_id}, type={typ}, balance={balance})")

    conn.commit()
    log.info(f"Accounts upserted: {len(lookup)}")
    return lookup


def upsert_transactions(conn, account_lookup):
    """For each account, fetch transactions and upsert. Skip pending. Flip sign for credit accounts."""
    sql = """
        INSERT INTO transactions (
            external_transaction_id, account_id, external_category, transaction_type,
            amount, description, merchant, status, transaction_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (external_transaction_id) DO NOTHING
    """
    total_seen = total_inserted = total_skipped_pending = 0

    with conn.cursor() as cur:
        for ext_account_id, (account_id, account_type) in account_lookup.items():
            txns = teller_get(f"/accounts/{ext_account_id}/transactions")
            log.info(f"Fetched {len(txns)} transactions for account {account_id}")
            total_seen += len(txns)

            for t in txns:
                if t['status'] == 'pending':
                    total_skipped_pending += 1
                    continue

                amount = Decimal(t['amount'])
                if account_type == 'credit':
                    amount = -amount

                counterparty = (t.get('details') or {}).get('counterparty') or {}

                cur.execute(sql, (
                    t['id'],
                    account_id,
                    (t.get('details') or {}).get('category'),
                    t.get('type'),
                    amount,
                    t.get('description'),
                    counterparty.get('name'),
                    t['status'],
                    t['date'],
                ))
                total_inserted += cur.rowcount

    conn.commit()
    log.info(f"Transactions seen: {total_seen}, inserted: {total_inserted}, skipped (pending): {total_skipped_pending}")


def main():
    log.info("=== Starting Teller ingest ===")
    log.info(f"Using cert: {CERT}")

    accounts = teller_get('/accounts')
    log.info(f"Fetched {len(accounts)} accounts from Teller")

    conn = build_db_conn()
    try:
        account_lookup = upsert_accounts(conn, accounts)
        upsert_transactions(conn, account_lookup)
    finally:
        conn.close()

    log.info("=== Teller ingest complete ===")


if __name__ == '__main__':
    main()
