-- One row per active account per day, from its first snapshot to today.
-- Days between two snapshots are interpolated linearly, so a hand-entered account
-- (401Ks) shows its growth spread over the months it happened rather than as one
-- jump on the update day. Days after the latest snapshot carry it forward.
with first_snapshots as (
    select account_id, min(snapshot_date) as first_date
    from {{ ref('fct_account_balances') }}
    group by 1
),

spine as (
    select f.account_id, d::date as date
    from first_snapshots f
    cross join lateral generate_series(f.first_date, current_date, interval '1 day') as d
),

-- prev_grp increments on each snapshot going forward in time, next_grp going
-- backward, so each day can find the snapshots on either side of it
grouped as (
    select
        s.account_id,
        s.date,
        b.balance,
        b.snapshot_date,
        count(b.balance) over (partition by s.account_id order by s.date)      as prev_grp,
        count(b.balance) over (partition by s.account_id order by s.date desc) as next_grp
    from spine s
    left join {{ ref('fct_account_balances') }} b
        on b.account_id = s.account_id
       and b.snapshot_date = s.date
),

neighbors as (
    select
        account_id,
        date,
        max(balance)       over (partition by account_id, prev_grp) as prev_balance,
        max(snapshot_date) over (partition by account_id, prev_grp) as prev_date,
        max(balance)       over (partition by account_id, next_grp) as next_balance,
        max(snapshot_date) over (partition by account_id, next_grp) as next_date
    from grouped
),

filled as (
    select
        account_id,
        date,
        case
            when next_date is null or next_date = prev_date then prev_balance
            else prev_balance + (next_balance - prev_balance)
                 * (date - prev_date)::numeric / (next_date - prev_date)
        end          as balance,
        -- date of the last real snapshot on or before this day
        prev_date    as snapshot_date
    from neighbors
)

select
    f.date,
    a.account_id,
    a.account_name,
    a.institution,
    a.account_type,
    a.owner,
    case
        when a.account_type in ('checking', 'savings', 'cash') then 'Cash'
        when a.account_name ~* '\m(401k|ira)\M' then 'Retirement'
        when a.account_type = 'investment' then 'Investments'
        when a.account_type = 'credit' then 'Credit Cards'
    end                       as account_group,
    a.is_linked,
    round(f.balance, 2)       as balance,
    -- liabilities subtract from net worth
    case a.account_type
        when 'credit' then -round(f.balance, 2)
        else round(f.balance, 2)
    end                       as net_worth_contribution,
    f.snapshot_date
from filled f
join {{ ref('dim_account') }} a using (account_id)
where a.is_active
