select
    account_id,
    external_account_id,
    name          as account_name,
    type          as account_type,
    institution,
    currency,
    owner,
    is_active
from {{ source('bronze', 'accounts') }}
