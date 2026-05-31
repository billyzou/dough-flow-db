-- Single-row model: avg monthly expense over last 12 fully completed calendar months.
-- Used as a flat reference line on the MTD cumulative spend chart.
with spine as (
    select generate_series(
        date_trunc('month', current_date)::date,
        current_date,
        interval '1 day'
    )::date as date
),

avg_monthly as (
    select
        abs(sum(amount)) / 12.0                   as avg_monthly_spend
    from {{ ref('stg_transactions') }}
    where
        category_type = 'expense'
        and category_name != 'Transfers'
        and transaction_type != 'special'
        and transaction_date >= date_trunc('month', current_date - interval '12 months')
        and transaction_date <  date_trunc('month', current_date)
)

select
    spine.date,
    avg_monthly.avg_monthly_spend
from spine
cross join avg_monthly
