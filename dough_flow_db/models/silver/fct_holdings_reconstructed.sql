-- Rebuilt holdings history, kept apart from fct_holdings (what Plaid actually reported). Each row
-- is the start of a day before a holding's first Plaid snapshot, like a morning snapshot: the
-- shares held then (tax lots bought before that day), their cost, and their value at the
-- previous trading day's Yahoo close. The lots come from the first snapshot, so shares sold
-- before it are missing from both value and cost.
--
-- Only holdings whose lots are complete: every lot dated, and their shares match the first
-- snapshot's. The lots can lag the snapshot by a few days of trades, so a match counts once trades
-- from the last 0-3 days before the snapshot are added (those trades are after every rebuilt day).
with first_snapshots as (
    select distinct on (account_id, security_id) account_id, security_id, snapshot_date as first_snapshot, quantity
    from {{ ref('fct_holdings') }}
    order by account_id, security_id, snapshot_date
),

lots as (
    select a.account_id, l.security_id, l.purchase_date, l.quantity, l.cost_basis
    from {{ ref('stg_plaid__tax_lots') }} l
    join {{ ref('stg_accounts') }} a using (external_account_id)
),

trades as (
    select a.account_id, t.security_id, t.transaction_date, t.quantity
    from {{ ref('stg_plaid__investment_transactions') }} t
    join {{ ref('stg_accounts') }} a using (external_account_id)
),

lot_totals as (
    select l.account_id, l.security_id, f.first_snapshot, f.quantity as snapshot_quantity,
           min(l.purchase_date) as first_lot, sum(l.quantity) as lot_quantity,
           count(*) = count(l.purchase_date) as all_dated
    from lots l
    join first_snapshots f using (account_id, security_id)
    group by 1, 2, 3, 4
),

complete as (
    select t.account_id, t.security_id, t.first_lot, t.first_snapshot
    from lot_totals t
    cross join generate_series(0, 3) lag_days
    where t.all_dated
      and abs(t.lot_quantity + coalesce((
              select sum(tr.quantity) from trades tr
              where tr.account_id = t.account_id and tr.security_id = t.security_id
                and tr.transaction_date >= t.first_snapshot - lag_days and tr.transaction_date < t.first_snapshot
          ), 0) - t.snapshot_quantity) < 0.0001
    group by 1, 2, 3, 4
),

held as (
    select c.account_id, c.security_id, d::date as snapshot_date,
           sum(l.quantity) as quantity, sum(l.cost_basis) as cost_basis
    from complete c
    cross join generate_series(c.first_lot + 1, c.first_snapshot - 1, interval '1 day') d
    join lots l on l.account_id = c.account_id and l.security_id = c.security_id and l.purchase_date < d::date
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
    where p.ticker = s.ticker and p.price_date < h.snapshot_date
    order by p.price_date desc
    limit 1
) p on true
