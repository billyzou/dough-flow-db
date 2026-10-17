-- Tax lots of each holding's first payload: the purchases behind the shares held at the first
-- snapshot. The first, not the latest, so later sales don't change the rebuilt history.
with first as (
    select distinct on (plaid_account_id, security_id) *
    from {{ source('bronze', 'plaid_holdings') }}
    order by plaid_account_id, security_id, loaded_at
)

select
    plaid_account_id                                     as external_account_id,
    security_id,
    left(lot->>'original_purchase_datetime', 10)::date   as purchase_date,
    (lot->>'quantity')::numeric                          as quantity,
    (lot->>'cost_basis')::numeric(15, 2)                 as cost_basis
from first
cross join jsonb_array_elements(coalesce(payload->'tax_lots', '[]')) lot
