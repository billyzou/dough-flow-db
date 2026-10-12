-- Latest version of each Plaid transaction, pending ones included.
with latest as (
    select distinct on (plaid_transaction_id) *
    from {{ source('bronze', 'plaid_transactions') }}
    order by plaid_transaction_id, loaded_at desc
)

select
    plaid_transaction_id                                         as transaction_id,
    payload->>'account_id'                                       as external_account_id,
    -- Plaid: positive = money out. Ours: negative = expense, positive = income.
    -(payload->>'amount')::numeric(15, 2)                        as amount,
    coalesce(payload->>'authorized_date', payload->>'date')::date as transaction_date,
    (payload->>'date')::date                                     as posted_date,
    payload->>'name'                                             as description,
    payload->>'merchant_name'                                    as merchant,
    payload->'personal_finance_category'->>'primary'             as external_category,
    payload->'personal_finance_category'->>'detailed'            as external_category_detailed,
    payload->>'transaction_type'                                 as transaction_type,
    (payload->>'pending')::boolean                               as is_pending,
    loaded_at
from latest
