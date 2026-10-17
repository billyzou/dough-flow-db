-- Rebuilt holdings history, kept apart from fct_holdings (what Plaid actually reported). For each
-- day before a holding's first Plaid snapshot: the shares held then (tax lots bought on or before
-- that day), their cost, and their value at that day's Yahoo close (the last close on weekends and
-- holidays). The lots only cover shares held now, so shares since sold are missing from both value
-- and cost. Only holdings whose lots are complete: every lot dated, and together they match the
-- latest snapshot's shares and cost basis.
with latest as (
    select distinct on (account_id, security_id) account_id, security_id, quantity, cost_basis
    from {{ ref('fct_holdings') }}
    order by account_id, security_id, snapshot_date desc
),

first_snapshots as (
    select account_id, security_id, min(snapshot_date) as first_snapshot
    from {{ ref('fct_holdings') }}
    group by 1, 2
),

lots as (
    select a.account_id, l.security_id, l.purchase_date, l.quantity, l.cost_basis
    from {{ ref('stg_plaid__tax_lots') }} l
    join {{ ref('stg_accounts') }} a using (external_account_id)
),

complete as (
    select l.account_id, l.security_id, min(l.purchase_date) as first_lot, f.first_snapshot
    from lots l
    join latest h using (account_id, security_id)
    join first_snapshots f using (account_id, security_id)
    group by l.account_id, l.security_id, h.quantity, h.cost_basis, f.first_snapshot
    having count(*) = count(l.purchase_date)
       and sum(l.quantity) = h.quantity
       and abs(sum(l.cost_basis) - h.cost_basis) < 1
),

held as (
    select c.account_id, c.security_id, d::date as snapshot_date,
           sum(l.quantity) as quantity, sum(l.cost_basis) as cost_basis
    from complete c
    cross join generate_series(c.first_lot, c.first_snapshot - 1, interval '1 day') d
    join lots l on l.account_id = c.account_id and l.security_id = c.security_id and l.purchase_date <= d::date
    group by 1, 2, 3
)

select
    h.account_id,
    h.security_id,
    h.snapshot_date,
    h.quantity,
    p.close                                  as price,
    (h.quantity * p.close)::numeric(15, 2)   as value,
    h.cost_basis::numeric(15, 2)             as cost_basis
from held h
join {{ ref('dim_security') }} s using (security_id)
left join lateral (
    select close from {{ ref('stg_yahoo__prices') }} p
    where p.ticker = s.ticker and p.price_date <= h.snapshot_date
    order by p.price_date desc
    limit 1
) p on true
