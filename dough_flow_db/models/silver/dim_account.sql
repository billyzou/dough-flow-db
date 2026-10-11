-- One row per account. Linked accounts take type and institution from their latest Plaid
-- payload; hand-entered ones from the registry. The registry's name is kept for both.
with latest_plaid as (
    select distinct on (external_account_id) *
    from {{ ref('stg_plaid__accounts') }}
    order by external_account_id, loaded_at desc
)

select
    a.account_id,
    a.external_account_id,
    a.account_name,
    coalesce(p.account_type, a.account_type) as account_type,
    coalesce(p.institution, a.institution)   as institution,
    coalesce(p.currency, a.currency)         as currency,
    a.owner,
    a.is_active,
    -- linked through Plaid (daily snapshots) vs entered by hand
    a.external_account_id is not null        as is_linked
from {{ ref('stg_accounts') }} a
left join latest_plaid p using (external_account_id)
