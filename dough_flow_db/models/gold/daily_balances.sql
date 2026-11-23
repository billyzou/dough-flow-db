-- One row per active account per day, from its first snapshot to today.
-- Days between two snapshots are interpolated linearly, so a hand-entered account
-- (401Ks) shows its growth spread over the months it happened rather than as one
-- jump on the update day. Days after the latest snapshot carry it forward.
--
-- Exception, outages only: a linked investment account's gap where the daily ingest had no
-- successful run on any day inside it (ops.pipeline_runs) follows SPY instead of a straight
-- line: each day moves with SPY's close, plus a steady correction so the gap still lands
-- exactly on the next snapshot. Falls back to linear where SPY has no price or a balance
-- isn't positive. Gaps before the run log starts are never treated as outages.
with first_snapshots as (
    select account_id, min(snapshot_date) as first_date
    from {{ ref('fct_account_balances') }}
    group by 1
),

ingest_days as (
    select distinct started_at::date as date
    from {{ source('ops', 'pipeline_runs') }}
    where success
),

-- SPY's last close before each day, like a morning snapshot (see fct_holdings_reconstructed)
spy as (
    select d::date as date,
           (select p.close from {{ ref('stg_yahoo__prices') }} p
            where p.ticker = 'SPY' and p.price_date < d::date
            order by p.price_date desc limit 1) as close
    from generate_series((select min(first_date) from first_snapshots), current_date, interval '1 day') d
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
        n.account_id,
        n.date,
        case
            when n.next_date is null or n.next_date = n.prev_date then n.prev_balance
            when a.account_type = 'investment' and a.is_linked
                 and n.prev_date >= (select min(date) from ingest_days)
                 and not exists (select 1 from ingest_days i
                                 where i.date > n.prev_date and i.date < n.next_date)
                 and s_prev.close > 0 and s_day.close > 0 and s_next.close > 0
                 and n.prev_balance > 0 and n.next_balance > 0
            then n.prev_balance * (s_day.close / s_prev.close)
                 * power((n.next_balance / n.prev_balance) / (s_next.close / s_prev.close),
                         (n.date - n.prev_date)::numeric / (n.next_date - n.prev_date))
            else n.prev_balance + (n.next_balance - n.prev_balance)
                 * (n.date - n.prev_date)::numeric / (n.next_date - n.prev_date)
        end          as balance,
        -- date of the last real snapshot on or before this day
        n.prev_date  as snapshot_date
    from neighbors n
    join {{ ref('dim_account') }} a using (account_id)
    left join spy s_day  on s_day.date  = n.date
    left join spy s_prev on s_prev.date = n.prev_date
    left join spy s_next on s_next.date = n.next_date
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
