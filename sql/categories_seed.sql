-- ============================================================
-- Category Taxonomy + Teller Mapping
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

-- Map Teller's details.category -> our category_id.
-- "service" is intentionally unmapped (too vague) — those rows stay NULL
-- until we see real merchant data and can categorize them properly.
INSERT INTO category_map (external_category, category_id)
SELECT v.external_category, c.category_id
FROM (VALUES
    ('groceries',      'Groceries'),
    ('dining',         'Food'),
    ('shopping',       'Shopping'),
    ('general',        'Shopping'),
    ('electronics',    'Shopping'),
    ('office',         'Shopping'),
    ('phone',          'Bills & Utilities'),
    ('utilities',      'Bills & Utilities'),
    ('software',       'Bills & Utilities'),
    ('transportation', 'Transport'),
    ('fuel',           'Transport'),
    ('accommodation',  'Travel'),
    ('entertainment',  'Entertainment'),
    ('home',           'Housing'),
    ('health',         'Personal Care')
) AS v(external_category, category_name)
JOIN categories c ON c.name = v.category_name
ON CONFLICT (external_category) DO NOTHING;
