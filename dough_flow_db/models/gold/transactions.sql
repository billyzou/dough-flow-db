-- Posted transactions with their account and category, for the dashboard and the
-- aggregates in this folder.
select
    t.transaction_id,
    t.transaction_date,
    t.amount,
    t.spend,
    t.description,
    t.merchant,
    t.external_category,
    t.transaction_type,
    a.account_id,
    a.account_name,
    a.institution,
    a.account_type,
    a.owner,
    c.category_id,
    c.category_name,
    c.category_type
from {{ ref('fct_transactions') }} t
join {{ ref('dim_account') }} a using (account_id)
left join {{ ref('dim_category') }} c using (category_id)
