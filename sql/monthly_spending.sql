-- Monthly spending and income, grouped by category.
-- Sign convention matches transactions: negative = expense, positive = income.
-- Uncategorized rows appear with category_name = NULL.

SELECT
    DATE_TRUNC('month', t.transaction_date)::date AS month,
    c.name        AS category_name,
    c.type        AS category_type,
    COUNT(*)      AS txn_count,
    SUM(t.amount) AS total
FROM transactions t
LEFT JOIN categories c 
    ON c.category_id = t.category_id
WHERE t.status = 'posted'
GROUP BY month, c.name, c.type
ORDER BY month DESC, total ASC;
