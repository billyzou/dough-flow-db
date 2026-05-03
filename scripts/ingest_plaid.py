#!/usr/bin/env python3
"""
ingest_plaid.py

Pulls accounts and transactions from Plaid and upserts them into Postgres.
Categorization is a separate step — run scripts/categorize.py after this.

Sign convention (matches CLAUDE.md): negative = expense, positive = income.
Plaid normalizes amount sign across account types (positive = money out from
the user's perspective), so we flip once on insert regardless of account type.
"""

import logging
import os
from datetime import date, timedelta

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


def map_account_type(plaid_type, plaid_subtype):
    if plaid_type == 'depository':
        return 'checking' if plaid_subtype == 'checking' else 'savings'
    if plaid_type == 'credit':
        return 'credit'
    if plaid_type == 'investment':
        return 'investment'
    return 'cash'


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


def upsert_accounts(conn, accounts, institution_name):
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
        for acct in accounts:
            a = acct.to_dict()
            balances = a.get('balances') or {}
            cur.execute(sql, (
                a['account_id'],
                a['name'],
                map_account_type(str(a.get('type', '')), str(a.get('subtype', '') or '')),
                institution_name,
                balances.get('iso_currency_code') or 'USD',
                balances.get('current') or 0,
            ))
            account_id, ext_id, typ = cur.fetchone()
            lookup[ext_id] = (account_id, typ)
            log.info(f"  Upserted account {a['name']} (local id={account_id}, type={typ})")

    conn.commit()
    log.info(f"  Accounts upserted: {len(lookup)}")
    return lookup


def upsert_transactions(conn, transactions, account_lookup):
    """Insert posted transactions; skip pending; flip Plaid's sign convention."""
    sql = """
        INSERT INTO transactions (
            external_transaction_id, account_id, external_category, transaction_type,
            amount, description, merchant, status, transaction_date, posted_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (external_transaction_id) DO NOTHING
    """
    seen = inserted = skipped_pending = skipped_no_account = 0

    with conn.cursor() as cur:
        for txn in transactions:
            t = txn.to_dict()
            seen += 1

            if t.get('pending'):
                skipped_pending += 1
                continue

            entry = account_lookup.get(t['account_id'])
            if entry is None:
                skipped_no_account += 1
                log.warning(f"  No local account for {t['account_id']}, skipping {t['transaction_id']}")
                continue
            local_account_id, _ = entry

            pfc = t.get('personal_finance_category') or {}
            cur.execute(sql, (
                t['transaction_id'],
                local_account_id,
                pfc.get('primary'),
                t.get('transaction_type'),
                -t['amount'],
                t.get('name'),
                t.get('merchant_name'),
                'posted',
                t.get('authorized_date') or t['date'],
                t['date'],
            ))
            inserted += cur.rowcount

    conn.commit()
    log.info(f"  Transactions seen: {seen}, inserted: {inserted}, skipped pending: {skipped_pending}, skipped no account: {skipped_no_account}")
    return seen, inserted, skipped_pending


def ingest_enrollment(conn, client, label, token, start_date, end_date):
    log.info(f"--- Ingesting enrollment: {label} ---")
    institution_name = fetch_institution_name(client, token)
    log.info(f"[{label}] Institution: {institution_name}")
    accounts, transactions = fetch_transactions(client, token, start_date, end_date)
    log.info(f"[{label}] Fetched {len(accounts)} accounts, {len(transactions)} transactions")
    account_lookup = upsert_accounts(conn, accounts, institution_name)
    return upsert_transactions(conn, transactions, account_lookup)


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
            try:
                seen, inserted, skipped = ingest_enrollment(
                    conn, client, label, token, start_date, end_date
                )
                grand_seen += seen
                grand_inserted += inserted
                grand_skipped += skipped
            except Exception as e:
                log.exception(f"[{label}] Ingest failed: {e}")
                failures.append(label)
                conn.rollback()
    finally:
        conn.close()

    log.info(
        f"=== Plaid ingest complete: seen={grand_seen}, inserted={grand_inserted}, "
        f"skipped_pending={grand_skipped}, failed_enrollments={failures or 'none'} ==="
    )
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
