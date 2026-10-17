-- Latest version of each Plaid investment transaction (buy, sell, dividend, fee, ...).
with latest as (
    select distinct on (investment_transaction_id) *
    from {{ source('bronze', 'plaid_investment_transactions') }}
    order by investment_transaction_id, loaded_at desc
)

select
    investment_transaction_id,
    payload->>'account_id'                   as external_account_id,
    payload->>'security_id'                  as security_id,
    (payload->>'date')::date                 as transaction_date,
    payload->>'type'                         as transaction_type,
    payload->>'subtype'                      as transaction_subtype,
    payload->>'name'                         as description,
    (payload->>'quantity')::numeric          as quantity,
    (payload->>'price')::numeric             as price,
    -- Plaid: positive = cash out of the account (a buy), negative = cash in (a sale, dividend)
    (payload->>'amount')::numeric(15, 2)     as amount,
    (payload->>'fees')::numeric(15, 2)       as fees,
    loaded_at
from latest
