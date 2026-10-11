-- Latest hand-entered balance per account per day.
select distinct on (account_id, snapshot_date)
    account_id,
    snapshot_date,
    balance,
    entered_at
from {{ source('bronze', 'manual_balances') }}
order by account_id, snapshot_date, entered_at desc
