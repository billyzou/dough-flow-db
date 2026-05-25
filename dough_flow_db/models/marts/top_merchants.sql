select
    merchant,
    -sum(amount)  as total_spent,
    count(*)      as transaction_count
from {{ ref('stg_transactions') }}
where category_type = 'expense'
  and merchant is not null
  and transaction_date >= current_date - interval '28 days'
group by 1
order by total_spent desc
