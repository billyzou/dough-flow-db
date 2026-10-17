-- Latest payload for each Plaid security.
with latest as (
    select distinct on (security_id) *
    from {{ source('bronze', 'plaid_securities') }}
    order by security_id, loaded_at desc
)

select
    security_id,
    payload->>'ticker_symbol'                as ticker,
    payload->>'name'                         as security_name,
    payload->>'type'                         as security_type,
    (payload->>'is_cash_equivalent')::boolean as is_cash_equivalent
from latest
