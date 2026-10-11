select
    transaction_id,
    category_id
from {{ source('bronze', 'category_overrides') }}
