-- Category spend comparison: MTD, prior year same month, YTD, prior YTD, 12-mo avg
-- One row per category. All amounts positive (expenses only).
with base as (
    select
        category_name,
        transaction_date,
        abs(amount)                               as amount
    from {{ ref('stg_transactions') }}
    where
        category_type = 'expense'
        and category_name != 'Transfers'
        and transaction_type != 'special'
        and category_name is not null
),

-- bounds
bounds as (
    select
        date_trunc('month', current_date)::date   as mtd_start,
        current_date                              as today,
        date_trunc('year', current_date)::date    as ytd_start,
        date_trunc('month', current_date - interval '1 year')::date  as prior_month_start,
        (date_trunc('month', current_date - interval '1 year')
            + interval '1 month' - interval '1 day')::date           as prior_month_end,
        date_trunc('year', current_date - interval '1 year')::date   as prior_ytd_start,
        -- prior YTD end = same day last year
        (current_date - interval '1 year')::date  as prior_ytd_end,
        date_trunc('month', current_date - interval '12 months')::date as avg_start,
        date_trunc('month', current_date)::date   as avg_end
)

select
    category_name,
    coalesce(sum(case when transaction_date >= b.mtd_start
             and transaction_date <= b.today
        then amount end), 0)                      as this_month,
    coalesce(sum(case when transaction_date >= b.prior_month_start
             and transaction_date <= b.prior_month_end
        then amount end), 0)                      as last_year_month,
    coalesce(sum(case when transaction_date >= b.ytd_start
             and transaction_date <= b.today
        then amount end), 0)                      as this_year,
    coalesce(sum(case when transaction_date >= b.prior_ytd_start
             and transaction_date <= b.prior_ytd_end
        then amount end), 0)                      as last_year,
    coalesce(sum(case when transaction_date >= b.avg_start
             and transaction_date <  b.avg_end
        then amount end), 0) / 12.0               as monthly_avg_12mo
from base, bounds b
group by category_name
order by this_month desc nulls last
