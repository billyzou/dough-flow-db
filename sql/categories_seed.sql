-- ============================================================
-- Category Taxonomy + Plaid Mapping
-- Idempotent — safe to re-run.
-- Run AFTER schema.sql.
-- ============================================================

-- Our category taxonomy (flat, 1:1 with Plaid PFC for now).
INSERT INTO categories (name, type) VALUES
    ('Food',          'expense'),
    ('Entertainment', 'expense'),
    ('Transport',     'expense'),
    ('Travel',        'expense'),
    ('Housing',       'expense'),
    ('Shopping',      'expense'),
    ('Personal Care', 'expense'),
    ('Loan Payments', 'expense'),
    ('Transfers',     'expense'),
    ('Income',        'income')
ON CONFLICT (name) DO NOTHING;

-- Map Plaid's personal_finance_category.primary -> our category_id.
INSERT INTO plaid_category_map (plaid_category, category_id)
SELECT v.plaid_category, c.category_id
FROM (VALUES
    ('FOOD_AND_DRINK',      'Food'),
    ('ENTERTAINMENT',       'Entertainment'),
    ('TRANSPORTATION',      'Transportation'),
    ('TRAVEL',              'Travel'),
    ('RENT_AND_UTILITIES',  'Housing'),
    ('GENERAL_MERCHANDISE', 'Shopping'),
    ('PERSONAL_CARE',       'Personal Care'),
    ('LOAN_PAYMENTS',       'Loan Payments'),
    ('TRANSFER_OUT',        'Transfers'),
    ('TRANSFER_IN',         'Transfers'),
    ('INCOME',              'Income')
) AS v(plaid_category, category_name)
JOIN categories c ON c.name = v.category_name
ON CONFLICT (plaid_category) DO NOTHING;
