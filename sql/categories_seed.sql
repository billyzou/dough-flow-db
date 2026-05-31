-- ============================================================
-- Category Taxonomy + Plaid PFC Mapping
-- Idempotent — safe to re-run.
-- Run AFTER schema.sql.
-- ============================================================

INSERT INTO categories (name, type) VALUES
    ('Food & Groceries',  'expense'),
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
    ('FOOD_AND_DRINK',      'Food & Groceries'),
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

-- Map CSV/Teller category labels -> our category_id.
-- These come from bank CSV exports and Teller's hierarchical labels.
-- 'OTHER' left unmapped (too varied).
INSERT INTO category_map (external_category, category_id)
SELECT v.external_category, c.category_id
FROM (VALUES
    ('Shopping',                                        'Shopping'),
    ('Groceries',                                       'Food & Groceries'),
    ('Food & Drink',                                    'Food & Groceries'),
    ('Travel',                                          'Travel'),
    ('Home',                                            'Housing'),
    ('Entertainment',                                   'Entertainment'),
    ('Personal',                                        'Personal Care'),
    ('Bills & Utilities',                               'Bills & Utilities'),
    ('Fees & Adjustments-Fees & Adjustments',           'Bills & Utilities'),
    ('BANK_FEES',                                       'Bills & Utilities'),
    ('LOAN_DISBURSEMENTS',                              'Transfers'),
    ('Merchandise & Supplies-Groceries',                'Food & Groceries'),
    ('Merchandise & Supplies-General Retail',           'Shopping'),
    ('Merchandise & Supplies-Department Stores',        'Shopping'),
    ('Merchandise & Supplies-Clothing Stores',          'Shopping'),
    ('Merchandise & Supplies-Electronics Stores',       'Shopping'),
    ('Merchandise & Supplies-Computer Supplies',        'Shopping'),
    ('Merchandise & Supplies-Sporting Goods Stores',    'Shopping'),
    ('Merchandise & Supplies-Hardware Supplies',        'Shopping'),
    ('Merchandise & Supplies-Wholesale Stores',         'Shopping'),
    ('Merchandise & Supplies-Arts & Jewelry',           'Shopping'),
    ('Merchandise & Supplies-Furnishing',               'Shopping'),
    ('Merchandise & Supplies-Florists & Garden',        'Shopping'),
    ('Merchandise & Supplies-Pharmacies',               'Personal Care'),
    ('Merchandise & Supplies-Internet Purchase',        'Shopping'),
    ('Restaurant-Restaurant',                           'Food & Groceries'),
    ('Restaurant-Bar & Café',                           'Food & Groceries'),
    ('Transportation-Taxis & Coach',                    'Transport'),
    ('Transportation-Rail Services',                    'Transport'),
    ('Transportation-Fuel',                             'Transport'),
    ('Transportation-Parking Charges',                  'Transport'),
    ('Transportation-Vehicle Leasing & Purchase',       'Transport'),
    ('Other-Government Services',                       'Transport'),
    ('Other-Miscellaneous',                             'Transfers'),
    ('Travel-Airline',                                  'Travel'),
    ('Travel-Lodging',                                  'Travel'),
    ('Travel-Travel Agencies',                          'Travel'),
    ('Entertainment-Other Entertainment',               'Entertainment'),
    ('Entertainment-General Events',                    'Entertainment'),
    ('Communications-Cable & Internet Comm',            'Bills & Utilities'),
    ('Communications-Telephone Comm',                   'Bills & Utilities'),
    ('Business Services-Office Supplies',               'Shopping'),
    ('Business Services-Professional Services',         'Shopping'),
    ('Business Services-Insurance Services',            'Bills & Utilities'),
    ('Business Services-Internet Services',             'Bills & Utilities')
) AS v(external_category, category_name)
JOIN categories c ON c.name = v.category_name
ON CONFLICT (external_category) DO NOTHING;
