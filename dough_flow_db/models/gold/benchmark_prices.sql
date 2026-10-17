-- Daily closes of the benchmark the performance charts compare against (SPY, the S&P 500).
-- Split-adjusted, not dividend-adjusted: a price return, like the portfolio's.
select price_date, close
from {{ ref('stg_yahoo__prices') }}
where ticker = 'SPY'
