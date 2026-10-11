with daily as (
    select
        transaction_date                          as date,
        category_type,
        sum(case category_type when 'income' then amount else spend end) as daily_total
    from {{ ref('transactions') }}
    where
        (category_type = 'income' or spend is not null)
        and transaction_date >= date_trunc('year', current_date - interval '1 year')
    group by 1, 2
),

-- spine covers this year only; prior year dates are shifted forward 1 year to align
spine as (
    select generate_series(
        date_trunc('year', current_date)::date,
        current_date,
        interval '1 day'
    )::date as date
),

date_types as (
    select spine.date, t.category_type
    from spine
    cross join (values ('income'), ('expense')) as t(category_type)
),

-- this year
current_year as (
    select
        dt.date,
        dt.category_type,
        extract(year from dt.date)::text          as year,
        coalesce(d.daily_total, 0)                as daily_total
    from date_types dt
    left join daily d using (date, category_type)
    where dt.date >= date_trunc('year', current_date)
),

-- prior year: shift each date forward 1 year to align on the same x-axis
prior_year as (
    select
        dt.date,
        dt.category_type,
        extract(year from dt.date - interval '1 year')::text as year,
        coalesce(d.daily_total, 0)                as daily_total
    from date_types dt
    left join daily d
        on d.date = (dt.date - interval '1 year')::date
       and d.category_type = dt.category_type
),

combined as (
    select * from current_year
    union all
    select * from prior_year
)

select
    date,
    year,
    category_type,
    sum(daily_total) over (
        partition by category_type, year
        order by date
        rows between unbounded preceding and current row
    )                                             as cumulative_total
from combined
order by date, year, category_type
