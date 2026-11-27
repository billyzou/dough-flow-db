#!/usr/bin/env python3
"""
plaid_freshness_test.py

One-off test: does Plaid have newer investment balances and prices in the afternoon than at the
10:00 UTC ingest? Pulls accounts and holdings for every enrollment with the investments product
and compares them with the latest ingested bronze snapshot (run it after that day's ingest). Read-only: writes nothing to the database,
so the day's silver snapshot stays the morning one.

Usage (in the Airflow container, which has the DB settings):
    docker exec dough-flow-db-airflow-scheduler-1 python /opt/airflow/scripts/plaid_freshness_test.py
The last line printed is a one-line summary.
"""
from plaid.model.accounts_get_request import AccountsGetRequest

from ingest_plaid import build_db_conn, build_plaid_client, discover_tokens, fetch_holdings, fetch_item


def morning_rows(conn, table, label, key_sql):
    """The enrollment's latest ingested snapshot: {key: payload}."""
    with conn.cursor() as cur:
        cur.execute(f"""
            select {key_sql}, payload from bronze.{table}
            where enrollment = %s and loaded_at = (
                select max(loaded_at) from bronze.{table} where enrollment = %s)
        """, (label, label))
        return {row[:-1]: row[-1] for row in cur.fetchall()}


def main():
    client, conn = build_plaid_client(), build_db_conn()
    changed_accts = total_accts = newer_prices = total_holdings = 0

    for label, token in sorted(discover_tokens().items()):
        _, products = fetch_item(client, token)
        if 'investments' not in products:
            continue
        print(f"--- {label} ---")

        before = morning_rows(conn, 'plaid_accounts', label, 'plaid_account_id')
        accounts = client.accounts_get(AccountsGetRequest(access_token=token))['accounts']
        for a in accounts:
            if str(a['type']) != 'investment':
                continue
            old = before.get((a['account_id'],))
            old_bal = old and old['balances']['current']
            new_bal = a['balances']['current']
            total_accts += 1
            changed_accts += old_bal != new_bal
            print(f"  account {a['name'][:30]:30} morning={old_bal}  now={new_bal}"
                  f"{'  CHANGED' if old_bal != new_bal else ''}")

        before = morning_rows(conn, 'plaid_holdings', label, 'plaid_account_id, security_id')
        holdings, _ = fetch_holdings(client, token)
        for h in holdings:
            old = before.get((h['account_id'], h['security_id']), {})
            old_asof, new_asof = old.get('institution_price_as_of'), h['institution_price_as_of']
            new_asof = new_asof and str(new_asof)
            total_holdings += 1
            newer = old_asof != new_asof
            newer_prices += newer
            print(f"  holding {h['security_id'][:12]:12} price_as_of morning={old_asof} now={new_asof}"
                  f"  price morning={old.get('institution_price')} now={h['institution_price']}"
                  f"{'  NEWER' if newer else ''}")

    conn.close()
    print(f"Plaid afternoon vs morning: {changed_accts}/{total_accts} investment balances changed, "
          f"{newer_prices}/{total_holdings} holdings have a newer price date")


if __name__ == '__main__':
    main()
