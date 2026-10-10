select
    date_trunc('month', transaction_date)::date as month,
    category_name,
    category_type,
    abs(sum(amount))                             as total,
    count(*)                                     as transaction_count
from {{ ref('stg_transactions') }}
where category_type = 'expense'
  and category_name != 'Transfers'
group by 1, 2, 3
order by 1 desc, total asc
