-- Tax lots of each holding's latest payload: the purchases behind the shares held now.
with latest as (
    select distinct on (plaid_account_id, security_id) *
    from {{ source('bronze', 'plaid_holdings') }}
    order by plaid_account_id, security_id, loaded_at desc
)

select
    plaid_account_id                                     as external_account_id,
    security_id,
    left(lot->>'original_purchase_datetime', 10)::date   as purchase_date,
    (lot->>'quantity')::numeric                          as quantity,
    (lot->>'cost_basis')::numeric(15, 2)                 as cost_basis
from latest
cross join jsonb_array_elements(coalesce(payload->'tax_lots', '[]')) lot
