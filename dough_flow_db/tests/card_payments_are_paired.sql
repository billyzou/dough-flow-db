-- Card payments land twice: out of checking and into the card. fct_transactions.spend
-- relies on the two halves cancelling, so every half needs a partner within a few days.
-- A row here usually means a bank link broke and only one side is coming through.
with payments as (
    select transaction_id, transaction_date, account_name, description, amount, account_type
    from {{ ref('transactions') }}
    where category_name = 'Loan Payments'
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
    where o.category_name = 'Loan Payments'
      and o.amount = -p.amount
      and (o.account_type = 'credit') != (p.account_type = 'credit')
      and abs(o.transaction_date - p.transaction_date) <= 5
)
