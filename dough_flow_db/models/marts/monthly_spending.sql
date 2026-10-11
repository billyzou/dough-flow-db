select
    date_trunc('month', transaction_date)::date as month,
    category_name,
    category_type,
    sum(spend)                                   as total,
    count(*)                                     as transaction_count
from {{ ref('stg_transactions') }}
where spend is not null
group by 1, 2, 3
order by 1 desc, total asc
