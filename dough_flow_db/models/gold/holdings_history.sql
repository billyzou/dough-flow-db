-- Value and cost basis per holding per day, for the performance chart. source says where a row
-- comes from: 'snapshot' is what Plaid reported (fct_holdings), 'reconstructed' is rebuilt from
-- tax lots and Yahoo prices before the first snapshot (fct_holdings_reconstructed).
with history as (
    select account_id, security_id, snapshot_date, quantity, price, value, cost_basis, 'snapshot' as source
    from {{ ref('fct_holdings') }}
    union all
    select account_id, security_id, snapshot_date, quantity, price, value, cost_basis, 'reconstructed'
    from {{ ref('fct_holdings_reconstructed') }}
)

select
    h.snapshot_date,
    h.source,
    a.institution || ' · ' || a.account_name as account,
    -- same rule as daily_balances' account_group
    case when a.account_name ~* '\m(401k|ira)\M' then 'Retirement' else 'Investments' end as account_group,
    s.security_type,
    case when s.security_type = 'cash' then 'Cash'  -- Plaid's ticker is CUR:USD
         else coalesce(s.ticker, s.security_name) end as ticker,
    h.quantity,
    h.price,
    h.value,
    h.cost_basis
from history h
join {{ ref('dim_account') }} a using (account_id)
join {{ ref('dim_security') }} s using (security_id)
