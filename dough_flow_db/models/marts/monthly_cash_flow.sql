select
    date_trunc('month', transaction_date)::date as month,
    category_type,
    sum(amount)                                  as total,
    count(*)                                     as transaction_count
from {{ ref('stg_transactions') }}
where category_type in ('income', 'expense')
  and category_name != 'Transfers'
group by 1, 2
order by 1 desc, 2
