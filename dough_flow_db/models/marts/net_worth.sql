with latest_balances as (
    select distinct on (account_id)
        account_id,
        snapshot_date,
        balance
    from account_balances
    order by account_id, snapshot_date desc
)
select
    a.account_id,
    a.name        as account_name,
    a.institution,
    a.type        as account_type,
    lb.balance,
    lb.snapshot_date,
    -- liabilities subtract from net worth
    case a.type
        when 'credit' then -lb.balance
        else lb.balance
    end           as net_worth_contribution
from latest_balances lb
join accounts a using (account_id)
where a.is_active
