-- Daily closes from Yahoo Finance, split-adjusted (scripts/backfill_prices.py).
select
    ticker,
    price_date,
    close
from {{ source('bronze', 'security_prices') }}
