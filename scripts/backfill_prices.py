#!/usr/bin/env python3
"""
backfill_prices.py

Fetches daily closing prices from Yahoo Finance for every ticker that has Plaid tax lots,
from its first purchase to today, plus the SPY benchmark, into bronze.security_prices. dbt multiplies them with the
lots to rebuild each holding's value before its first Plaid snapshot
(silver.fct_holdings_reconstructed).

Not part of the daily DAG: history before the first snapshot doesn't change. Re-run it after
linking a new investment account, or after a split (Yahoo's closes are split-adjusted, so a
split changes every earlier close). Then run dbt.

Usage (in the Airflow container, which has the DB settings):
    docker exec dough-flow-db-airflow-scheduler-1 python /opt/airflow/scripts/backfill_prices.py
"""
import logging
import os
from datetime import date, datetime, time, timedelta, timezone

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'


def fetch_closes(ticker, start, end):
    """Return {date: close} for trading days from start to end. close is split-adjusted only."""
    resp = requests.get(
        CHART_URL.format(ticker=ticker),
        params={
            'period1': int(datetime.combine(start, time(), timezone.utc).timestamp()),
            'period2': int(datetime.combine(end + timedelta(days=1), time(), timezone.utc).timestamp()),
            'interval': '1d',
        },
        headers={'User-Agent': 'Mozilla/5.0'},  # Yahoo rejects requests without one
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()['chart']['result'][0]
    # timestamps are each day's market open, so the UTC date is the trading day
    days = [datetime.fromtimestamp(t, timezone.utc).date() for t in result.get('timestamp', [])]
    closes = result['indicators']['quote'][0]['close']
    return {d: c for d, c in zip(days, closes) if c is not None}


def main():
    conn = psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )
    with conn.cursor() as cur:
        # plus the SPY benchmark, from the first purchase of anything
        cur.execute("""
            with lots as (
                select s.ticker, l.purchase_date
                from silver.stg_plaid__tax_lots l
                join silver.dim_security s using (security_id)
                where s.ticker is not null and s.security_type <> 'cash' and l.purchase_date is not null
            )
            select ticker, min(purchase_date)
            from (select * from lots union all select 'SPY', min(purchase_date) from lots) t
            group by ticker
            order by ticker
        """)
        tickers = cur.fetchall()
    log.info(f"Fetching prices for {len(tickers)} tickers")

    failures = []
    for ticker, start in tickers:
        try:
            closes = fetch_closes(ticker, start, date.today())
            with conn.cursor() as cur:
                for d, close in closes.items():
                    cur.execute("""
                        INSERT INTO bronze.security_prices (ticker, price_date, close)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (ticker, price_date) DO UPDATE SET close = EXCLUDED.close, loaded_at = NOW()
                    """, (ticker, d, close))
            conn.commit()
            log.info(f"  {ticker}: {len(closes)} days from {start}")
        except Exception:
            conn.rollback()
            log.exception(f"  {ticker}: failed")
            failures.append(ticker)

    conn.close()
    log.info(f"Done. failed={failures or 'none'}")
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
