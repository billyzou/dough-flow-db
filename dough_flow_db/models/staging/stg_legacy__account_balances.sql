select
    account_id,
    snapshot_date,
    currency,
    balance
from {{ source('bronze', 'legacy_account_balances') }}
