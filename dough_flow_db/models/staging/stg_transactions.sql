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
    c.type         as category_type
from transactions t
join accounts a using (account_id)
left join categories c using (category_id)
where t.status = 'posted'
