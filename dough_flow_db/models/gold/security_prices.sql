-- Daily closes by ticker; the rolling-return charts use SPY as the S&P 500 benchmark.
-- Split-adjusted, not dividend-adjusted: price returns, like the portfolio's.
select ticker, price_date, close
from {{ ref('stg_yahoo__prices') }}
