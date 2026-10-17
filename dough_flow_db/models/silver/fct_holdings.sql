-- One row per account per security per day that has a Plaid holdings snapshot.
select
    a.account_id,
    h.security_id,
    h.snapshot_date,
    h.quantity,
    h.price,
    h.value,
    h.cost_basis
from {{ ref('stg_plaid__holdings') }} h
join {{ ref('stg_accounts') }} a using (external_account_id)
