-- Money put into investment and retirement accounts each month, so the Net Worth tab can tell
-- market gains apart from money added. Two sources:
--   * transfers from the Wealthfront cash account into its investing accounts, net of money moved
--     back (Wealthfront labels both directions CROSS_ACCOUNT_TRANSFER)
--   * 401K contributions reported by the brokerage (Plaid: negative amount = cash in)
with transfers as (
    select transaction_date, -amount as amount
    from {{ ref('fct_transactions') }}
    where description ilike '%CROSS_ACCOUNT_TRANSFER%'
),

contributions as (
    select transaction_date, -amount as amount
    from {{ ref('stg_plaid__investment_transactions') }}
    where transaction_type = 'cash'
      and transaction_subtype = 'contribution'
)

select
    date_trunc('month', transaction_date)::date as month,
    sum(amount)                                  as deposits
from (
    select * from transfers
    union all
    select * from contributions
) moved
group by 1
order by 1 desc
