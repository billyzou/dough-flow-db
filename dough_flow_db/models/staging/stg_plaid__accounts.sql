-- One row per Plaid account per day: the last payload loaded that day.
with daily as (
    select distinct on (plaid_account_id, loaded_at::date) *
    from {{ source('bronze', 'plaid_accounts') }}
    order by plaid_account_id, loaded_at::date, loaded_at desc
)

select
    plaid_account_id                                             as external_account_id,
    enrollment,
    institution_name                                             as institution,
    payload->>'name'                                             as plaid_name,
    case payload->>'type'
        when 'depository' then
            case when payload->>'subtype' = 'checking' then 'checking' else 'savings' end
        when 'credit'     then 'credit'
        when 'investment' then 'investment'
        else 'cash'
    end                                                          as account_type,
    coalesce(payload->'balances'->>'iso_currency_code', 'USD')   as currency,
    coalesce((payload->'balances'->>'current')::numeric(15, 2), 0) as balance,
    loaded_at::date                                              as snapshot_date,
    loaded_at
from daily
