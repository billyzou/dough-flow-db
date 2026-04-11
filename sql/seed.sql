-- ============================================================
-- Seed Data — Personal Finance Database
-- Run AFTER schema.sql
-- ============================================================

INSERT INTO accounts (name, type, institution, currency, balance) VALUES
    ('Main Checking',     'checking',   'Chase',    'USD',  3500.00),
    ('Emergency Savings', 'savings',    'Marcus',   'USD', 12000.00),
    ('Visa Credit Card',  'credit',     'Chase',    'USD',  -840.50),
    ('Brokerage',         'investment', 'Fidelity', 'USD', 25000.00),
    ('Cash Wallet',       'cash',        NULL,      'USD',   120.00);

INSERT INTO categories (name, type, color) VALUES
    ('Salary',            'income',  '#4CAF50'),
    ('Freelance',         'income',  '#8BC34A'),
    ('Investment Returns','income',  '#009688'),
    ('Housing',           'expense', '#F44336'),
    ('Food',              'expense', '#FF9800'),
    ('Transport',         'expense', '#FF5722'),
    ('Utilities',         'expense', '#3F51B5'),
    ('Entertainment',     'expense', '#9C27B0');

INSERT INTO categories (name, type, parent_id, color)
    SELECT 'Groceries',  'expense', id, '#FFC107' FROM categories WHERE name = 'Food';
INSERT INTO categories (name, type, parent_id, color)
    SELECT 'Restaurants','expense', id, '#FFEB3B' FROM categories WHERE name = 'Food';
INSERT INTO categories (name, type, parent_id, color)
    SELECT 'Gas',        'expense', id, '#FF7043' FROM categories WHERE name = 'Transport';

INSERT INTO transactions (account_id, category_id, amount, description, merchant, transaction_date, is_recurring)
SELECT a.id, (SELECT id FROM categories WHERE name='Salary'), 5200.00,
    'Monthly salary deposit', 'Employer Inc.', CURRENT_DATE - INTERVAL '25 days', TRUE
FROM accounts a WHERE a.name = 'Main Checking';

INSERT INTO transactions (account_id, category_id, amount, description, merchant, transaction_date)
SELECT a.id, (SELECT id FROM categories WHERE name='Groceries'), -87.43,
    'Weekly grocery run', 'Whole Foods', CURRENT_DATE - INTERVAL '3 days'
FROM accounts a WHERE a.name = 'Main Checking';

INSERT INTO transactions (account_id, category_id, amount, description, merchant, transaction_date, is_recurring)
SELECT a.id, (SELECT id FROM categories WHERE name='Housing'), -1850.00,
    'Monthly rent', 'Landlord LLC', CURRENT_DATE - INTERVAL '10 days', TRUE
FROM accounts a WHERE a.name = 'Main Checking';

INSERT INTO budgets (category_id, amount, period, start_date)
SELECT id, 2000.00, 'monthly', DATE_TRUNC('month', CURRENT_DATE) FROM categories WHERE name = 'Housing';
INSERT INTO budgets (category_id, amount, period, start_date)
SELECT id, 600.00,  'monthly', DATE_TRUNC('month', CURRENT_DATE) FROM categories WHERE name = 'Food';
INSERT INTO budgets (category_id, amount, period, start_date)
SELECT id, 300.00,  'monthly', DATE_TRUNC('month', CURRENT_DATE) FROM categories WHERE name = 'Transport';
INSERT INTO budgets (category_id, amount, period, start_date)
SELECT id, 150.00,  'monthly', DATE_TRUNC('month', CURRENT_DATE) FROM categories WHERE name = 'Entertainment';
