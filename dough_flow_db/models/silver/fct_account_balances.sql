-- One row per account per day that has a real balance snapshot (not interpolated; see
-- gold/daily_balances). When sources overlap on a day, the most recently recorded wins,
-- so new Plaid and hand-entered snapshots replace the legacy copy.
with snapshots as (
    select account_id, snapshot_date, currency, balance,
           '-infinity'::timestamptz as recorded_at, 'legacy' as source
    from {{ ref('stg_legacy__account_balances') }}

    union all

    select a.account_id, p.snapshot_date, p.currency, p.balance,
           p.loaded_at, 'plaid'
    from {{ ref('stg_plaid__accounts') }} p
    join {{ ref('stg_accounts') }} a using (external_account_id)

    union all

    select m.account_id, m.snapshot_date, a.currency, m.balance,
           m.entered_at, 'manual'
    from {{ ref('stg_manual__balances') }} m
    join {{ ref('stg_accounts') }} a using (account_id)
)

select distinct on (account_id, snapshot_date)
    account_id,
    snapshot_date,
    currency,
    balance,
    source
from snapshots
order by account_id, snapshot_date, recorded_at desc
