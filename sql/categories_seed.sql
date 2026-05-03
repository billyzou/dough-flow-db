-- ============================================================
-- Category Taxonomy + Plaid PFC Mapping
-- Idempotent — safe to re-run.
-- Run AFTER schema.sql.
-- ============================================================

INSERT INTO categories (name, type) VALUES
    ('Groceries',         'expense'),
    ('Food',              'expense'),
    ('Shopping',          'expense'),
    ('Bills & Utilities', 'expense'),
    ('Transport',         'expense'),
    ('Travel',            'expense'),
    ('Entertainment',     'expense'),
    ('Housing',           'expense'),
    ('Personal Care',     'expense'),
    ('Loan Payments',     'expense'),
    ('Transfers',         'expense'),
    ('Income',            'income')
ON CONFLICT (name) DO NOTHING;

-- Remove stale Teller mappings (lowercase labels no longer appear in data).
DELETE FROM category_map WHERE external_category IN (
    'groceries', 'dining', 'shopping', 'general', 'electronics',
    'office', 'phone', 'utilities', 'software', 'transportation',
    'fuel', 'accommodation', 'entertainment', 'home', 'health'
);

-- Map Plaid's Personal Finance Category (PFC) primary labels -> our category_id.
-- We store pfc.primary on ingest; this drives categorize.py.
-- GOVERNMENT_AND_NON_PROFIT and BANK_FEES left unmapped (too varied; revisit
-- once real transaction data shows clear patterns).
INSERT INTO category_map (external_category, category_id)
SELECT v.external_category, c.category_id
FROM (VALUES
    ('FOOD_AND_DRINK',      'Food'),
    ('TRANSPORTATION',      'Transport'),
    ('TRAVEL',              'Travel'),
    ('ENTERTAINMENT',       'Entertainment'),
    ('GENERAL_MERCHANDISE', 'Shopping'),
    ('GENERAL_SERVICES',    'Shopping'),
    ('RENT_AND_UTILITIES',  'Bills & Utilities'),
    ('LOAN_PAYMENTS',       'Loan Payments'),
    ('PERSONAL_CARE',       'Personal Care'),
    ('MEDICAL',             'Personal Care'),
    ('HOME_IMPROVEMENT',    'Housing'),
    ('INCOME',              'Income'),
    ('TRANSFER_IN',         'Transfers'),
    ('TRANSFER_OUT',        'Transfers')
) AS v(external_category, category_name)
JOIN categories c ON c.name = v.category_name
ON CONFLICT (external_category) DO NOTHING;
