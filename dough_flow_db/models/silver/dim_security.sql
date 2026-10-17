select
    security_id,
    ticker,
    security_name,
    security_type,
    is_cash_equivalent
from {{ ref('stg_plaid__securities') }}
