#!/usr/bin/env python3
"""
ingest_transactions.py

Pulls accounts and transactions from Plaid and upserts them into dough_flow_db.
Safe to re-run — accounts update their balance, transactions skip on conflict.

Requires in .env:
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, PLAID_ACCESS_TOKEN
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

To get a sandbox PLAID_ACCESS_TOKEN: run explore_plaid.ipynb and copy the
access_token printed in Step 3, then add it to .env.
"""

import logging
import os
from datetime import date, timedelta

import psycopg2
from dotenv import load_dotenv

import plaid
from plaid.api import plaid_api
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

PLAID_ENV_MAP = {
    'sandbox':    plaid.Environment.Sandbox,
    'production': plaid.Environment.Production,
}


def map_account_type(plaid_type, plaid_subtype):
    """Map Plaid account type/subtype to our schema's type enum."""
    if plaid_type == 'depository':
        return 'checking' if plaid_subtype == 'checking' else 'savings'
    if plaid_type == 'credit':
        return 'credit'
    if plaid_type == 'investment':
        return 'investment'
    return 'cash'


def build_plaid_client():
    env_name = os.environ.get('PLAID_ENV', 'sandbox').lower()
    config = plaid.Configuration(
        host=PLAID_ENV_MAP.get(env_name, plaid.Environment.Sandbox),
        api_key={
            'clientId': os.environ['PLAID_CLIENT_ID'],
            'secret':   os.environ['PLAID_SECRET'],
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(config))


def build_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def fetch_plaid_data(client, access_token, start_date, end_date):
    """Fetch all accounts and transactions, paginating until complete."""
    log.info(f"Fetching transactions from {start_date} to {end_date}")
    all_transactions = []
    offset = 0

    while True:
        response = client.transactions_get(
            TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date,
                options=TransactionsGetRequestOptions(count=500, offset=offset),
            )
        )
        all_transactions.extend(response['transactions'])
        total = response['total_transactions']
        log.info(f"  Fetched {len(all_transactions)}/{total} transactions")
        if len(all_transactions) >= total:
            break
        offset += len(response['transactions'])

    return response['accounts'], all_transactions


def upsert_accounts(conn, accounts):
    """
    Upsert accounts; update balance on conflict.
    Returns a dict mapping plaid_account_id -> local account_id.
    """
    log.info(f"Upserting {len(accounts)} accounts...")
    sql = """
        INSERT INTO accounts (plaid_account_id, name, type, currency, balance)
        VALUES (%(plaid_account_id)s, %(name)s, %(type)s, %(currency)s, %(balance)s)
        ON CONFLICT (plaid_account_id) DO UPDATE SET
            balance    = EXCLUDED.balance,
            updated_at = NOW()
        RETURNING plaid_account_id, account_id
    """
    account_id_map = {}
    with conn.cursor() as cur:
        for acct in accounts:
            a = acct.to_dict()
            balances = a.get('balances') or {}
            cur.execute(sql, {
                'plaid_account_id': a['account_id'],
                'name':             a['name'],
                'type':             map_account_type(str(a.get('type', '')), str(a.get('subtype', '') or '')),
                'currency':         balances.get('iso_currency_code') or 'USD',
                'balance':          balances.get('current') or 0,
            })
            plaid_id, local_id = cur.fetchone()
            account_id_map[plaid_id] = local_id
    conn.commit()
    log.info(f"  Accounts done: {len(account_id_map)}")
    return account_id_map


def upsert_transactions(conn, transactions, account_id_map):
    """
    Insert posted transactions; skip on conflict (idempotent re-runs).
    Amount sign is flipped from Plaid's convention:
      Plaid positive = money out = we store as negative (expense).
      Plaid negative = money in  = we store as positive (income).
    """
    sql = """
        INSERT INTO transactions (
            account_id, plaid_transaction_id, plaid_category,
            amount, description, merchant, status,
            transaction_date, posted_date
        ) VALUES (
            %(account_id)s, %(plaid_transaction_id)s, %(plaid_category)s,
            %(amount)s, %(description)s, %(merchant)s, %(status)s,
            %(transaction_date)s, %(posted_date)s
        )
        ON CONFLICT (plaid_transaction_id) DO NOTHING
    """
    inserted = skipped_pending = skipped_no_account = 0

    with conn.cursor() as cur:
        for txn in transactions:
            t = txn.to_dict()

            if t.get('pending'):
                skipped_pending += 1
                continue

            local_account_id = account_id_map.get(t['account_id'])
            if local_account_id is None:
                log.warning(f"  No local account for plaid_account_id={t['account_id']}, skipping {t['transaction_id']}")
                skipped_no_account += 1
                continue

            pfc = t.get('personal_finance_category') or {}
            cur.execute(sql, {
                'account_id':           local_account_id,
                'plaid_transaction_id': t['transaction_id'],
                'plaid_category':       pfc.get('primary'),
                'amount':               -t['amount'],
                'description':          t.get('name'),
                'merchant':             t.get('merchant_name'),
                'status':               'posted',
                'transaction_date':     t.get('authorized_date') or t['date'],
                'posted_date':          t['date'],
            })
            inserted += cur.rowcount

    conn.commit()
    log.info(f"  Transactions inserted: {inserted} | skipped pending: {skipped_pending} | skipped no account: {skipped_no_account}")


def main():
    access_token = os.environ.get('PLAID_ACCESS_TOKEN')
    if not access_token:
        raise SystemExit(
            "PLAID_ACCESS_TOKEN not set in .env.\n"
            "Run explore_plaid.ipynb and copy the access_token from Step 3 output,\n"
            "then add: PLAID_ACCESS_TOKEN=access-sandbox-... to your .env file."
        )

    start_date = date.today() - timedelta(days=30)
    end_date   = date.today()

    log.info("=== Starting Plaid ingestion ===")
    client = build_plaid_client()
    conn   = build_db_conn()

    try:
        accounts, transactions = fetch_plaid_data(client, access_token, start_date, end_date)
        account_id_map = upsert_accounts(conn, accounts)
        upsert_transactions(conn, transactions, account_id_map)
    finally:
        conn.close()

    log.info("=== Ingestion complete ===")


if __name__ == '__main__':
    main()
