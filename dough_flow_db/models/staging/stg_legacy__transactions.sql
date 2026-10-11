-- category_id is left out: categories come from category_map plus category_overrides.
-- is_recurring and notes were never filled in.
select
    external_transaction_id as transaction_id,
    account_id,
    amount,
    transaction_date,
    posted_date,
    description,
    merchant,
    external_category,
    transaction_type,
    status = 'pending'      as is_pending
from {{ source('bronze', 'legacy_transactions') }}
