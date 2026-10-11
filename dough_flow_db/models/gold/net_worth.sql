with latest_balances as (
    select distinct on (account_id)
        account_id,
        snapshot_date,
        balance
    from {{ ref('fct_account_balances') }}
    order by account_id, snapshot_date desc
)
select
    a.account_id,
    a.account_name,
    a.institution,
    a.account_type,
    lb.balance,
    lb.snapshot_date,
    -- liabilities subtract from net worth
    case a.account_type
        when 'credit' then -lb.balance
        else lb.balance
    end           as net_worth_contribution
from latest_balances lb
join {{ ref('dim_account') }} a using (account_id)
where a.is_active
