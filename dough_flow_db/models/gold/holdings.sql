-- Every holdings snapshot with its account and security; the dashboard shows the latest day.
-- Gain is unrealized and only where the institution reports a cost basis.
select
    h.snapshot_date,
    a.account_id,
    a.institution || ' · ' || a.account_name as account,
    a.owner,
    case when s.security_type = 'cash' then 'Cash'  -- Plaid's ticker is CUR:USD
         else coalesce(s.ticker, s.security_name) end as ticker,
    s.security_name,
    s.security_type,
    h.quantity,
    h.price,
    h.value,
    h.cost_basis,
    h.value - h.cost_basis                   as gain,
    (h.value - h.cost_basis) / h.cost_basis  as gain_pct
from {{ ref('fct_holdings') }} h
join {{ ref('dim_account') }} a using (account_id)
join {{ ref('dim_security') }} s using (security_id)
