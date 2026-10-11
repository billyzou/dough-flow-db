-- One row per posted transaction. Plaid's latest payload wins; legacy rows fill in what
-- Plaid no longer returns (the 2025 CSV backfill, and anything older than its window).
with plaid as (
    select
        t.transaction_id,
        a.account_id,
        t.amount,
        t.transaction_date,
        t.posted_date,
        t.description,
        t.merchant,
        t.external_category,
        t.transaction_type,
        'plaid'  as source
    from {{ ref('stg_plaid__transactions') }} t
    join {{ ref('stg_accounts') }} a using (external_account_id)
    where not t.is_pending
),

legacy as (
    select
        transaction_id,
        account_id,
        amount,
        transaction_date,
        posted_date,
        description,
        merchant,
        external_category,
        transaction_type,
        'legacy' as source
    from {{ ref('stg_legacy__transactions') }} l
    where not is_pending
      and not exists (select 1 from plaid p where p.transaction_id = l.transaction_id)
),

unioned as (
    select * from plaid
    union all
    select * from legacy
)

select
    u.transaction_id,
    u.account_id,
    coalesce(o.category_id, m.category_id)  as category_id,
    u.transaction_date,
    u.posted_date,
    u.amount,
    -- Single definition of spending: every expense except Transfers, money out positive,
    -- refunds negative. Card payments land in Loan Payments twice (out of checking, into
    -- the card) and cancel; tests/card_payments_are_paired.sql guards that.
    case when c.category_type = 'expense' and c.category_name != 'Transfers' then -u.amount end as spend,
    u.description,
    u.merchant,
    u.external_category,
    u.transaction_type,
    u.source
from unioned u
left join {{ ref('stg_category_overrides') }} o using (transaction_id)
left join {{ ref('category_map') }} m using (external_category)
left join {{ ref('dim_category') }} c on c.category_id = coalesce(o.category_id, m.category_id)
