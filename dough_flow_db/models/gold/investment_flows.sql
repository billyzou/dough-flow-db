-- Money moved into (positive) or out of each investment account per day, as the brokerage reports
-- it: deposits, transfers and 401K contributions. Dividends aren't counted: they're a return, not
-- money added. The Net Worth tab's What Changed table takes these out of an account's change to
-- leave its market gain or loss.
select
    t.transaction_date                         as date,
    a.institution || ' · ' || a.account_name   as account,
    -sum(t.amount)                             as amount   -- Plaid: negative amount = cash in
from {{ ref('stg_plaid__investment_transactions') }} t
join {{ ref('stg_accounts') }} a using (external_account_id)
where t.transaction_type = 'transfer'
   or (t.transaction_type = 'cash' and t.transaction_subtype in ('deposit', 'contribution', 'withdrawal'))
group by 1, 2
