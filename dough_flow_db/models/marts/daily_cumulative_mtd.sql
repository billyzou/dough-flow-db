with spine as (
    select generate_series(
        date_trunc('month', current_date)::date,
        current_date,
        interval '1 day'
    )::date as date
),

-- daily expense totals for current month
current_daily as (
    select
        transaction_date                          as date,
        sum(abs(amount))                          as daily_total
    from {{ ref('stg_transactions') }}
    where
        category_type = 'expense'
        and category_name != 'Transfers'
        and transaction_type != 'special'
        and transaction_date >= date_trunc('month', current_date)
    group by 1
),

-- daily expense totals for same month last year, shifted forward 1 year
prior_daily as (
    select
        (transaction_date + interval '1 year')::date as date,
        sum(abs(amount))                              as daily_total
    from {{ ref('stg_transactions') }}
    where
        category_type = 'expense'
        and category_name != 'Transfers'
        and transaction_type != 'special'
        and transaction_date >= date_trunc('month', current_date - interval '1 year')
        and transaction_date <  date_trunc('month', current_date)
    group by 1
),

-- avg monthly expense over last 12 fully completed calendar months
avg_monthly as (
    select abs(sum(amount)) / 12.0 as avg_monthly_spend
    from {{ ref('stg_transactions') }}
    where
        category_type = 'expense'
        and category_name != 'Transfers'
        and transaction_type != 'special'
        and transaction_date >= date_trunc('month', current_date - interval '12 months')
        and transaction_date <  date_trunc('month', current_date)
),

joined as (
    select
        spine.date,
        coalesce(c.daily_total, 0) as current_daily,
        coalesce(p.daily_total, 0) as prior_daily
    from spine
    left join current_daily c using (date)
    left join prior_daily  p using (date)
)

select
    date,
    sum(current_daily) over (
        order by date
        rows between unbounded preceding and current row
    )                                             as this_month,
    sum(prior_daily) over (
        order by date
        rows between unbounded preceding and current row
    )                                             as prior_year_month,
    (select avg_monthly_spend from avg_monthly)   as avg_monthly_spend
from joined
order by date
