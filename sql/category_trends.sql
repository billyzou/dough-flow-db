-- Month-over-month change per category, with calendar gaps filled (missing months -> 0).
-- Sign convention matches transactions: negative = expense, positive = income.

WITH bounds AS (
    SELECT
        DATE_TRUNC('month', MIN(transaction_date))::date AS min_month,
        DATE_TRUNC('month', MAX(transaction_date))::date AS max_month
    FROM transactions
    WHERE status = 'posted'
),
months AS (
    SELECT generate_series(min_month, max_month, interval '1 month')::date AS month
    FROM bounds
),
cats AS (
    SELECT DISTINCT c.name AS category_name, c.type AS category_type
    FROM transactions t
    LEFT JOIN categories c ON c.category_id = t.category_id
    WHERE t.status = 'posted'
),
grid AS (
    SELECT m.month, c.category_name, c.category_type
    FROM months m
    CROSS JOIN cats c
),
monthly AS (
    SELECT
        DATE_TRUNC('month', t.transaction_date)::date AS month,
        c.name        AS category_name,
        c.type        AS category_type,
        SUM(t.amount) AS total
    FROM transactions t
    LEFT JOIN categories c ON c.category_id = t.category_id
    WHERE t.status = 'posted'
    GROUP BY month, c.name, c.type
),
filled AS (
    SELECT
        g.month,
        g.category_name,
        g.category_type,
        COALESCE(m.total, 0) AS total
    FROM grid g
    LEFT JOIN monthly m
        ON m.month = g.month
       AND m.category_name IS NOT DISTINCT FROM g.category_name
       AND m.category_type IS NOT DISTINCT FROM g.category_type
)
SELECT
    month,
    category_name,
    category_type,
    total,
    LAG(total)     OVER w AS prev_month_total,
    total - LAG(total)     OVER w AS mom_delta,
    (total - LAG(total) OVER w)
        / NULLIF(ABS(LAG(total) OVER w), 0) AS mom_pct_change,
    LAG(total, 12) OVER w AS prev_year_total,
    total - LAG(total, 12) OVER w AS yoy_delta,
    (total - LAG(total, 12) OVER w)
        / NULLIF(ABS(LAG(total, 12) OVER w), 0) AS yoy_pct_change
FROM filled
WINDOW w AS (PARTITION BY category_name, category_type ORDER BY month)
ORDER BY category_name, month DESC;
