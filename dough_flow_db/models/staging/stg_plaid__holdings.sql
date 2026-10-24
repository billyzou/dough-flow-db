-- One row per Plaid holding (account + security) per day: the last ingest run that day.
with daily as (
    select distinct on (plaid_account_id, security_id, loaded_at::date) *
    from {{ source('bronze', 'plaid_holdings') }}
    order by plaid_account_id, security_id, loaded_at::date, loaded_at desc
),

holdings as (
    select
        plaid_account_id                                     as external_account_id,
        security_id,
        enrollment,
        (payload->>'quantity')::numeric                      as quantity,
        (payload->>'institution_price')::numeric             as price,
        (payload->>'institution_value')::numeric(15, 2)      as value,
        -- Plaid sends 0 or nothing when the institution doesn't know what was paid. Then use the tax
        -- lots, but only when they cover every share (some brokerages send lots but no total)
        coalesce(
            nullif((payload->>'cost_basis')::numeric(15, 2), 0),
            case when lots.quantity = (payload->>'quantity')::numeric then lots.cost_basis end
        )                                                    as cost_basis,
        loaded_at::date                                      as snapshot_date,
        loaded_at
    from daily
    left join lateral (
        select sum((lot->>'quantity')::numeric)              as quantity,
               sum((lot->>'cost_basis')::numeric)::numeric(15, 2) as cost_basis
        from jsonb_array_elements(coalesce(payload->'tax_lots', '[]')) lot
    ) lots on true
)

select
    external_account_id,
    security_id,
    enrollment,
    quantity,
    price,
    value,
    -- a new purchase can reach the share count a day before its tax lot does, leaving that day
    -- without a cost basis: carry the previous day's over rather than drop the holding from it
    coalesce(cost_basis, lag(cost_basis) over (
        partition by external_account_id, security_id order by snapshot_date
    ))                                                       as cost_basis,
    snapshot_date,
    loaded_at
from holdings
