with recent as (
    select *
    from {{ ref('transactions') }}
    where category_type = 'expense'
      and category_name != 'Transfers'
      and transaction_date >= current_date - interval '28 days'
)

select
    merchant,
    -sum(amount)  as total_spent,
    count(*)      as transaction_count,
    -- share of all spend in the window, including charges with no merchant
    -sum(amount) / (select -sum(amount) from recent) as share_of_spend
from recent
where merchant is not null
group by 1
order by total_spent desc
