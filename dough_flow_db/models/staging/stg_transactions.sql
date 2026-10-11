select
    t.transaction_id,
    t.transaction_date,
    t.amount,
    t.description,
    t.merchant,
    t.external_category,
    t.transaction_type,
    t.is_recurring,
    t.notes,
    a.account_id,
    a.name         as account_name,
    a.institution,
    a.type         as account_type,
    a.owner,
    c.category_id,
    c.name         as category_name,
    c.type         as category_type,
    -- Single definition of spending: every expense except Transfers, money out positive,
    -- refunds negative. Card payments land in Loan Payments twice (out of checking, into
    -- the card) and cancel; tests/card_payments_are_paired.sql guards that.
    case when c.type = 'expense' and c.name != 'Transfers' then -t.amount end as spend
from transactions t
join accounts a using (account_id)
left join categories c using (category_id)
where t.status = 'posted'
