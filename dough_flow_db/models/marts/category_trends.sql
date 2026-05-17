select
    date_trunc('month', transaction_date)::date as month,
    category_name,
    sum(amount)                                  as total,
    count(*)                                     as transaction_count
from {{ ref('stg_transactions') }}
where
    category_type = 'expense'
    and transaction_date >= date_trunc('month', current_date - interval '11 months')
group by 1, 2
order by 1 desc, 2
