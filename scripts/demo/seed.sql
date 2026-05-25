-- ─────────────────────────────────────────────────────────────────────
-- Public demo synthetic dataset
-- ─────────────────────────────────────────────────────────────────────
--
-- Run on a dedicated Postgres database (NOT the application DB).
-- Each demo Space gets a SpaceConnection pointing here read-only.
-- One copy serves every visitor — the data is generated, not real.
--
-- Shape: small e-commerce store. Wide enough that the AI chat can
-- answer the kind of questions a marketing/sales prospect actually
-- asks ("top customers", "monthly revenue", "average order value",
-- "best-selling category", "churn-risk accounts").
--
-- Provision:
--   psql "$DEMO_DB_URL" -f scripts/demo/seed.sql
--
-- Re-run:
--   The script is idempotent (TRUNCATE before INSERT) so the cleanup
--   cron can call it nightly to wipe vandalism without touching the
--   schema.
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS customers (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    country      TEXT NOT NULL,
    plan         TEXT NOT NULL CHECK (plan IN ('starter', 'pro', 'enterprise')),
    signup_date  DATE NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS products (
    id        SERIAL PRIMARY KEY,
    sku       TEXT UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    placed_at    TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled', 'refunded')),
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0)
);

CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INT NOT NULL REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(10, 2) NOT NULL,
    line_total  NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

CREATE INDEX IF NOT EXISTS idx_orders_placed_at  ON orders (placed_at);
CREATE INDEX IF NOT EXISTS idx_orders_customer   ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

-- Reset to a clean state every run.
TRUNCATE order_items, orders, products, customers RESTART IDENTITY CASCADE;

-- ─── Customers (40) ────────────────────────────────────────────────────
INSERT INTO customers (name, email, country, plan, signup_date, is_active) VALUES
('Northwind Traders',   'orders@northwind.example',     'US', 'enterprise', '2024-08-12', TRUE),
('Acme Corp',           'finance@acme.example',         'US', 'pro',        '2024-09-03', TRUE),
('Globex Industries',   'ap@globex.example',            'CA', 'enterprise', '2024-09-14', TRUE),
('Initech',             'billing@initech.example',      'US', 'starter',    '2024-10-01', TRUE),
('Soylent Green',       'orders@soylent.example',       'US', 'pro',        '2024-10-19', TRUE),
('Umbrella Corp',       'finance@umbrella.example',     'JP', 'enterprise', '2024-11-02', TRUE),
('Wayne Enterprises',   'ap@wayne.example',             'US', 'enterprise', '2024-11-08', TRUE),
('Stark Industries',    'billing@stark.example',        'US', 'enterprise', '2024-11-22', TRUE),
('Cyberdyne Systems',   'orders@cyberdyne.example',     'US', 'pro',        '2024-12-04', TRUE),
('Tyrell Corporation',  'finance@tyrell.example',       'US', 'enterprise', '2024-12-15', TRUE),
('Wonka Industries',    'ap@wonka.example',             'UK', 'pro',        '2025-01-04', TRUE),
('Dunder Mifflin',      'billing@dunder.example',       'US', 'starter',    '2025-01-12', TRUE),
('Pied Piper',          'orders@piedpiper.example',     'US', 'starter',    '2025-01-23', TRUE),
('Hooli',               'finance@hooli.example',        'US', 'enterprise', '2025-02-02', TRUE),
('Aperture Science',    'ap@aperture.example',          'US', 'pro',        '2025-02-14', TRUE),
('Black Mesa',          'billing@blackmesa.example',    'US', 'pro',        '2025-02-26', TRUE),
('Vandelay Industries', 'orders@vandelay.example',      'US', 'starter',    '2025-03-08', TRUE),
('Bluth Company',       'finance@bluth.example',        'US', 'starter',    '2025-03-19', FALSE),
('Wernham Hogg',        'ap@wernham.example',           'UK', 'pro',        '2025-03-29', TRUE),
('Sterling Cooper',     'billing@sterlingcooper.example','US', 'enterprise', '2025-04-09', TRUE),
('Los Pollos Hermanos', 'orders@pollos.example',        'MX', 'pro',        '2025-04-21', TRUE),
('Buy More',            'finance@buymore.example',      'US', 'starter',    '2025-05-02', TRUE),
('Krusty Krab',         'ap@krustykrab.example',        'US', 'starter',    '2025-05-12', TRUE),
('Springfield Nuclear', 'billing@springfield.example',  'US', 'enterprise', '2025-05-24', TRUE),
('Globo Gym',           'orders@globogym.example',      'US', 'pro',        '2025-06-04', TRUE),
('Sirius Cybernetics',  'finance@sirius.example',       'UK', 'enterprise', '2025-06-15', TRUE),
('Massive Dynamic',     'ap@massivedynamic.example',    'US', 'enterprise', '2025-06-26', TRUE),
('Veridian Dynamics',   'billing@veridian.example',     'US', 'pro',        '2025-07-08', TRUE),
('Reynholm Industries', 'orders@reynholm.example',      'UK', 'starter',    '2025-07-19', TRUE),
('Oscorp',              'finance@oscorp.example',       'US', 'enterprise', '2025-07-30', TRUE),
('LexCorp',             'ap@lexcorp.example',           'US', 'enterprise', '2025-08-10', TRUE),
('Daily Planet',        'billing@dailyplanet.example',  'US', 'pro',        '2025-08-21', TRUE),
('Rekall',              'orders@rekall.example',        'US', 'starter',    '2025-09-01', FALSE),
('Spacely Sprockets',   'finance@spacely.example',      'US', 'pro',        '2025-09-12', TRUE),
('Cogswell Cogs',       'ap@cogswell.example',          'US', 'pro',        '2025-09-23', TRUE),
('Nakatomi Trading',    'billing@nakatomi.example',     'JP', 'enterprise', '2025-10-04', TRUE),
('Yoyodyne Propulsion', 'orders@yoyodyne.example',      'US', 'enterprise', '2025-10-15', TRUE),
('Acme Laboratories',   'finance@acmelabs.example',     'US', 'pro',        '2025-10-26', TRUE),
('Scranton Branch',     'ap@scranton.example',          'US', 'starter',    '2025-11-06', TRUE),
('Donut Stop',          'billing@donutstop.example',    'CA', 'starter',    '2025-11-17', TRUE);

-- ─── Products (20) ─────────────────────────────────────────────────────
INSERT INTO products (sku, name, category, unit_price) VALUES
('SKY-A1', 'Pulse Annual Plan',         'Subscription',   1199.00),
('SKY-A2', 'Pulse Quarterly Plan',      'Subscription',    349.00),
('SKY-A3', 'Pulse Monthly Plan',        'Subscription',    129.00),
('SKY-B1', 'Sky Compass Onboarding',    'Service',         499.00),
('SKY-B2', 'Sky Compass Power Hours',   'Service',          89.00),
('SKY-B3', 'Sky Compass Data Migration','Service',         749.00),
('SKY-C1', 'Connector Pack — Sales',    'Add-on',           49.00),
('SKY-C2', 'Connector Pack — Marketing','Add-on',           49.00),
('SKY-C3', 'Connector Pack — Finance',  'Add-on',           69.00),
('SKY-C4', 'Connector Pack — HR',       'Add-on',           49.00),
('SKY-D1', 'Premium Support — Bronze',  'Support',         199.00),
('SKY-D2', 'Premium Support — Silver',  'Support',         499.00),
('SKY-D3', 'Premium Support — Gold',    'Support',         999.00),
('SKY-E1', 'Storage Bundle 100GB',      'Add-on',           19.00),
('SKY-E2', 'Storage Bundle 1TB',        'Add-on',          129.00),
('SKY-F1', 'AI Beats — 10k',            'Usage',            29.00),
('SKY-F2', 'AI Beats — 50k',            'Usage',           129.00),
('SKY-F3', 'AI Beats — 250k',           'Usage',           549.00),
('SKY-G1', 'Custom Branding',           'Add-on',          299.00),
('SKY-G2', 'Audit Log Export',          'Add-on',           39.00);

-- ─── Orders + items — generated ────────────────────────────────────────
-- ~600 orders across the last ~14 months, weighted toward enterprise
-- customers buying more, recent months trending up. Each order has 1-4
-- line items.
DO $$
DECLARE
    cust RECORD;
    prod RECORD;
    n_orders INT;
    o_id INT;
    o_at TIMESTAMPTZ;
    o_status TEXT;
    o_total NUMERIC := 0;
    n_items INT;
    qty INT;
    plan_weight INT;
    -- Rolling random helpers; using gen_random_uuid for variety.
BEGIN
    FOR cust IN SELECT * FROM customers WHERE is_active LOOP
        plan_weight := CASE cust.plan
                        WHEN 'enterprise' THEN 35
                        WHEN 'pro' THEN 18
                        ELSE 8 END;
        n_orders := plan_weight + (random() * 10)::INT;
        FOR i IN 1..n_orders LOOP
            -- Spread across the 14 months ending today.
            o_at := NOW() - ((random() * 420)::INT || ' days')::INTERVAL
                          - ((random() * 86400)::INT || ' seconds')::INTERVAL;
            o_status := (ARRAY['paid','paid','paid','shipped','shipped','pending','cancelled','refunded'])
                        [1 + (random() * 7)::INT];
            INSERT INTO orders (customer_id, placed_at, status, total_amount)
                 VALUES (cust.id, o_at, o_status, 0)
              RETURNING id INTO o_id;
            o_total := 0;
            n_items := 1 + (random() * 3)::INT;
            FOR j IN 1..n_items LOOP
                SELECT * INTO prod FROM products ORDER BY random() LIMIT 1;
                qty := 1 + (random() * 5)::INT;
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                     VALUES (o_id, prod.id, qty, prod.unit_price);
                o_total := o_total + (qty * prod.unit_price);
            END LOOP;
            UPDATE orders SET total_amount = o_total WHERE id = o_id;
        END LOOP;
    END LOOP;
END $$;

COMMIT;

-- Sanity counts (run interactively to verify):
-- SELECT 'customers' AS table, count(*) FROM customers
-- UNION ALL SELECT 'products',  count(*) FROM products
-- UNION ALL SELECT 'orders',    count(*) FROM orders
-- UNION ALL SELECT 'order_items', count(*) FROM order_items;
