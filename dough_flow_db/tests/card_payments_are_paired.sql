-- Card payments land twice, both in Transfers: out of checking and into the card. Every half
-- needs a partner within a few days; a row here usually means a bank link broke and only one
-- side is coming through.
with payments as (
    select transaction_id, transaction_date, account_name, description, amount, account_type
    from {{ ref('transactions') }}
    where category_name = 'Transfers'
      -- Plaid's card payment labels; other transfers needn't be paired
      and external_category in ('LOAN_PAYMENTS', 'LOAN_DISBURSEMENTS')
      and transaction_type = 'special'
      and ((account_type = 'credit' and amount > 0) or (account_type != 'credit' and amount < 0))
      -- give the other side time to post
      and transaction_date < current_date - 5
)

select p.*
from payments p
where not exists (
    select 1
    from {{ ref('transactions') }} o
    where o.category_name = 'Transfers'
      and o.external_category in ('LOAN_PAYMENTS', 'LOAN_DISBURSEMENTS')
      and o.amount = -p.amount
      and (o.account_type = 'credit') != (p.account_type = 'credit')
      and abs(o.transaction_date - p.transaction_date) <= 5
)
