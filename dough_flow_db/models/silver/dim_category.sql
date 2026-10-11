select
    category_id,
    name    as category_name,
    type    as category_type
from {{ ref('categories') }}
