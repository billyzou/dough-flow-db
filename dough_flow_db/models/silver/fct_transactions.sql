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
        t.external_category_detailed,
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
        null     as external_category_detailed,
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
),

-- Amex Platinum statement credits go to the category of what they pay for, so each nets out
-- against its charge there. Plaid and the CSV backfill label them all over the place.
-- (Plaid's Walmart+ credits arrive named just "Walmart" and already land in Shopping.)
credits as (
    select
        u.*,
        case
            when d ilike 'platinum digital entertainment credit%'      then 7  -- Entertainment
            when d ilike 'platinum walmart+ credit%'
              or d ilike 'platinum lululemon credit%'
              or d ilike 'platinum saks credit%'                       then 3  -- Shopping
            when d ilike 'platinum uber one credit%'                   then 5  -- Transport
            when d ilike 'platinum resy credit%'                       then 2  -- Food & Groceries
            when d ilike 'platinum hotel credit%'
              or d ilike 'amex clear plus credit%'
              or d ilike 'amex travel pay with points credit%'         then 6  -- Travel
        end as credit_category_id
    from unioned u
    cross join lateral (select regexp_replace(u.description, '\s+', ' ', 'g') as d) n
)

select
    u.transaction_id,
    u.account_id,
    coalesce(o.category_id, u.credit_category_id, md.category_id, m.category_id) as category_id,
    u.transaction_date,
    u.posted_date,
    u.amount,
    -- Single definition of spending: every expense except Transfers, money out positive,
    -- refunds negative. Card payments are Transfers: the purchases count in their own categories.
    case when c.category_type = 'expense' and c.category_name != 'Transfers' then -u.amount end as spend,
    u.description,
    -- PayPal charges arrive without a merchant, described as "PAYPAL *<payee>"
    coalesce(u.merchant, case when u.description ilike 'paypal%' then 'PayPal' end) as merchant,
    u.external_category,
    u.transaction_type,
    u.source
from credits u
left join {{ ref('stg_category_overrides') }} o using (transaction_id)
-- a detailed label (e.g. gyms within PERSONAL_CARE) wins over the primary one
left join {{ ref('category_map') }} md on md.external_category = u.external_category_detailed
left join {{ ref('category_map') }} m on m.external_category = u.external_category
left join {{ ref('dim_category') }} c on c.category_id = coalesce(o.category_id, u.credit_category_id, md.category_id, m.category_id)
