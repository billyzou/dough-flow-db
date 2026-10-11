#!/usr/bin/env python3
"""
ingest_plaid.py

Pulls accounts and transactions from Plaid and lands them in bronze as raw JSON.
Cleaning (sign flip, pending filter, categories) happens in dbt, not here.
New Plaid accounts are also registered in bronze.accounts so they get an account_id.
"""

import hashlib
import json
import logging
import os
from datetime import date, timedelta, datetime

import psycopg2
from dotenv import load_dotenv

import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.products import Products
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

TOKEN_PREFIX = 'PLAID_TOKEN_'

PLAID_ENV_MAP = {
    'sandbox':    plaid.Environment.Sandbox,
    'production': plaid.Environment.Production,
}


def discover_tokens():
    """Return {label: token} for every env var matching PLAID_TOKEN_<LABEL>."""
    return {
        k[len(TOKEN_PREFIX):]: v
        for k, v in os.environ.items()
        if k.startswith(TOKEN_PREFIX) and v
    }


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


def fetch_institution_name(client, access_token):
    item = client.item_get(ItemGetRequest(access_token=access_token))['item']
    inst_id = item['institution_id']
    if not inst_id:
        return None
    inst = client.institutions_get_by_id(
        InstitutionsGetByIdRequest(
            institution_id=inst_id,
            country_codes=[CountryCode('US')],
        )
    )['institution']
    return inst['name']


def fetch_transactions(client, access_token, start_date, end_date):
    """Fetch all accounts and transactions, paginating until complete."""
    all_txns = []
    offset = 0
    accounts = None

    while True:
        resp = client.transactions_get(
            TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date,
                options=TransactionsGetRequestOptions(count=500, offset=offset),
            )
        )
        if accounts is None:
            accounts = resp['accounts']
        all_txns.extend(resp['transactions'])
        total = resp['total_transactions']
        log.info(f"  Fetched {len(all_txns)}/{total} transactions")
        if len(all_txns) >= total:
            break
        offset += len(resp['transactions'])

    return accounts, all_txns


def to_json(plaid_model):
    # sort_keys so an unchanged payload always hashes the same
    return json.dumps(plaid_model.to_dict(), sort_keys=True, default=str)


def land_accounts(conn, label, accounts, institution_name):
    """Register new accounts and store each account's payload (balances included)."""
    with conn.cursor() as cur:
        for acct in accounts:
            # name is only set on first sight: hand-entered accounts later linked to Plaid keep theirs
            cur.execute("""
                INSERT INTO bronze.accounts (external_account_id, name)
                VALUES (%s, %s)
                ON CONFLICT (external_account_id) DO NOTHING
            """, (acct['account_id'], acct['name']))
            cur.execute("""
                INSERT INTO bronze.plaid_accounts (enrollment, institution_name, plaid_account_id, payload)
                VALUES (%s, %s, %s, %s)
            """, (label, institution_name, acct['account_id'], to_json(acct)))

    conn.commit()
    log.info(f"  Accounts landed: {len(accounts)}")


def land_transactions(conn, label, transactions):
    """Store each transaction's payload, pending ones included. Unchanged payloads are skipped."""
    sql = """
        INSERT INTO bronze.plaid_transactions (plaid_transaction_id, payload_hash, enrollment, payload)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (plaid_transaction_id, payload_hash) DO NOTHING
    """
    seen = inserted = 0

    with conn.cursor() as cur:
        for txn in transactions:
            payload = to_json(txn)
            cur.execute(sql, (
                txn['transaction_id'],
                hashlib.md5(payload.encode()).hexdigest(),
                label,
                payload,
            ))
            seen += 1
            inserted += cur.rowcount

    conn.commit()
    unchanged = seen - inserted
    log.info(f"  Transactions seen: {seen}, new or changed: {inserted}, unchanged: {unchanged}")
    return seen, inserted, unchanged


def ingest_enrollment(conn, client, label, token, start_date, end_date):
    log.info(f"--- Ingesting enrollment: {label} ---")
    institution_name = fetch_institution_name(client, token)
    log.info(f"[{label}] Institution: {institution_name}")
    accounts, transactions = fetch_transactions(client, token, start_date, end_date)
    log.info(f"[{label}] Fetched {len(accounts)} accounts, {len(transactions)} transactions")
    land_accounts(conn, label, accounts, institution_name)
    return land_transactions(conn, label, transactions)


def insert_pipeline_runs(conn, enrollment, started_at, finished_at, success, error_message, rows_seen, rows_inserted, rows_skipped):
    """Insert pipeline runs. rows_skipped = transactions already in bronze unchanged."""
    sql = """
        INSERT INTO ops.pipeline_runs (
            enrollment, started_at, finished_at, success, error_message, rows_seen, rows_inserted, rows_skipped
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    with conn.cursor() as cur:
        cur.execute(sql, (
            enrollment, 
            started_at, 
            finished_at, 
            success, 
            error_message, 
            rows_seen, 
            rows_inserted, 
            rows_skipped
        ))
    
    conn.commit()


def main():
    log.info("=== Starting Plaid ingest ===")

    tokens = discover_tokens()
    if not tokens:
        log.error(f"No tokens found. Set one or more {TOKEN_PREFIX}<LABEL> env vars in .env.")
        return 1

    log.info(f"Found {len(tokens)} enrollment(s): {sorted(tokens)}")

    start_date = date.today() - timedelta(days=730)
    end_date   = date.today()

    client = build_plaid_client()
    conn = build_db_conn()
    failures = []
    grand_seen = grand_inserted = grand_skipped = 0
    try:
        for label, token in tokens.items():
            started_at = None
            try:
                started_at = datetime.now()
                seen, inserted, skipped = ingest_enrollment(
                    conn, client, label, token, start_date, end_date
                )
                finished_at = datetime.now()
                insert_pipeline_runs(conn=conn, enrollment=label, started_at=started_at, finished_at=finished_at, success=True, error_message=None, rows_seen=seen, rows_inserted=inserted, rows_skipped=skipped)
                grand_seen += seen
                grand_inserted += inserted
                grand_skipped += skipped

            except Exception as e:
                finished_at = datetime.now()
                error_message = f"[{label}] Ingest failed: {e}"
                log.exception(error_message)
                failures.append(label)
                conn.rollback()
                insert_pipeline_runs(conn=conn, enrollment=label, started_at=started_at, finished_at=finished_at, success=False, error_message=error_message, rows_seen=None, rows_inserted=None, rows_skipped=None)

    finally:
        conn.close()

    log.info(
        f"=== Plaid ingest complete: seen={grand_seen}, inserted={grand_inserted}, "
        f"unchanged={grand_skipped}, failed_enrollments={failures or 'none'} ==="
    )
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
