-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Distribuição / Retalho
-- ─────────────────────────────────────────────────────────────────
-- Existe porque a demo pública só tinha um sector. Quem escolhia
-- "Distribuição / Retalho" recebia perguntas sobre lugares de
-- subscrição e contas enterprise — e um prospect que vende ao balcão
-- percebe em dois segundos que aquilo não é sobre ele.
--
-- Quatro esquemas, as tabelas que este negócio tem mesmo. As perguntas
-- que valem a pena aqui atravessam-nos: a margem está nas vendas, o
-- dinheiro parado está no armazém, e o atraso está no fornecedor. Cada
-- um sabe uma parte; nenhum sabe a frase inteira.
--
--   sales.orders / order_lines   — o que saiu e por quanto
--   catalog.products             — custo e preço, para haver margem
--   inventory.stock              — o que está parado, e onde
--   supply.suppliers / receipts  — quem prometeu e quando entregou
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS supply;

CREATE TABLE IF NOT EXISTS supply.suppliers (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    country       TEXT NOT NULL,
    lead_time_days INT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog.products (
    id           SERIAL PRIMARY KEY,
    sku          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    family       TEXT NOT NULL,
    supplier_id  INT REFERENCES supply.suppliers(id),
    unit_cost    NUMERIC(10,2) NOT NULL,
    list_price   NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory.warehouses (
    id     SERIAL PRIMARY KEY,
    name   TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory.stock (
    id            SERIAL PRIMARY KEY,
    product_id    INT NOT NULL REFERENCES catalog.products(id),
    warehouse_id  INT NOT NULL REFERENCES inventory.warehouses(id),
    quantity      INT NOT NULL,
    last_movement DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS sales.customers (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    channel  TEXT NOT NULL,
    region   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales.orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES sales.customers(id),
    ordered_at   DATE NOT NULL,
    status       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales.order_lines (
    id          SERIAL PRIMARY KEY,
    order_id    INT NOT NULL REFERENCES sales.orders(id),
    product_id  INT NOT NULL REFERENCES catalog.products(id),
    quantity    INT NOT NULL,
    unit_price  NUMERIC(10,2) NOT NULL,
    discount    NUMERIC(5,4) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS supply.receipts (
    id           SERIAL PRIMARY KEY,
    supplier_id  INT NOT NULL REFERENCES supply.suppliers(id),
    product_id   INT NOT NULL REFERENCES catalog.products(id),
    promised_at  DATE NOT NULL,
    received_at  DATE,
    quantity     INT NOT NULL
);

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE supply.receipts, sales.order_lines, sales.orders, sales.customers,
         inventory.stock, inventory.warehouses, catalog.products, supply.suppliers
    RESTART IDENTITY CASCADE;

-- 8 fornecedores, com prazos de entrega diferentes de propósito: é a
-- diferença entre eles que faz a pergunta do atraso valer a pena.
INSERT INTO supply.suppliers (name, country, lead_time_days)
SELECT
    (ARRAY['Nordwind Supply','Ibérica Distribuição','Atlas Trading','Meridian Goods',
           'Delta Import','Vega Logística','Orion Partners','Pinnacle Sourcing'])[g],
    (ARRAY['DE','PT','ES','NL','IT','PT','PL','FR'])[g],
    (ARRAY[14, 5, 21, 10, 28, 7, 35, 12])[g]
FROM generate_series(1, 8) g;

-- 60 produtos em 6 famílias. A margem varia por família — e há uma
-- família inteira onde o desconto médio a come, que é o achado.
INSERT INTO catalog.products (sku, name, family, supplier_id, unit_cost, list_price)
SELECT
    'SKU-' || LPAD(g::TEXT, 4, '0'),
    (ARRAY['Bebidas','Mercearia','Limpeza','Higiene','Congelados','Papelaria'])[1 + g % 6]
        || ' ref. ' || g,
    (ARRAY['Bebidas','Mercearia','Limpeza','Higiene','Congelados','Papelaria'])[1 + g % 6],
    1 + g % 8,
    (2 + (g * 7) % 40)::NUMERIC(10,2),
    -- Margem bruta entre 18% e 55%, conforme a família.
    ((2 + (g * 7) % 40) * (1.18 + ((g % 6) * 0.075)))::NUMERIC(10,2)
FROM generate_series(1, 60) g;

INSERT INTO inventory.warehouses (name, region)
SELECT
    (ARRAY['Armazém Norte','Armazém Centro','Armazém Sul','Plataforma Lisboa'])[g],
    (ARRAY['Norte','Centro','Sul','Lisboa'])[g]
FROM generate_series(1, 4) g;

-- Stock: a maioria mexeu há pouco, mas há um bolso parado há mais de
-- meio ano — dinheiro em prateleira que ninguém contabiliza como custo.
INSERT INTO inventory.stock (product_id, warehouse_id, quantity, last_movement)
SELECT
    p.id,
    1 + (p.id + w) % 4,
    CASE WHEN p.id % 9 = 0 THEN 80 + (p.id * 13) % 300 ELSE 5 + (p.id * 7) % 90 END,
    CASE
        WHEN p.id % 9 = 0 THEN CURRENT_DATE - (200 + (p.id * 3) % 160)
        ELSE CURRENT_DATE - ((p.id * 5) % 45)
    END
FROM catalog.products p
CROSS JOIN generate_series(1, 2) w;

INSERT INTO sales.customers (name, channel, region)
SELECT
    (ARRAY['Mercado','Talho','Café','Restaurante','Mini-mercado','Padaria','Hotel','Escola',
           'Ginásio','Clínica'])[1 + g % 10] || ' ' || (ARRAY['Aurora','Bela Vista','Central',
           'do Norte','Oriente','Praia','Ribeira','Serra','Vale','Verde'])[1 + (g / 10) % 10],
    (ARRAY['revenda','horeca','retalho','online'])[1 + g % 4],
    (ARRAY['Norte','Centro','Sul','Lisboa'])[1 + g % 4]
FROM generate_series(1, 100) g;

-- 18 meses de encomendas, com crescimento e ruído sazonal.
INSERT INTO sales.orders (customer_id, ordered_at, status)
SELECT
    1 + (g * 17) % 100,
    (CURRENT_DATE - INTERVAL '18 months' + (g % 540) * INTERVAL '1 day')::DATE,
    CASE WHEN g % 23 = 0 THEN 'cancelled' ELSE 'delivered' END
FROM generate_series(1, 1200) g;

-- Linhas: 1 a 3 por encomenda. O desconto é maior nos Congelados —
-- é aí que a margem desaparece sem ninguém dar por isso.
INSERT INTO sales.order_lines (order_id, product_id, quantity, unit_price, discount)
SELECT
    o.id,
    p.id,
    1 + (o.id + p.id) % 12,
    p.list_price,
    CASE WHEN p.family = 'Congelados' THEN 0.18 + ((o.id % 7) * 0.015)
         ELSE ((o.id + p.id) % 6) * 0.01 END
FROM sales.orders o
JOIN LATERAL (
    SELECT id, list_price, family FROM catalog.products
    WHERE id IN (1 + (o.id * 7) % 60, 1 + (o.id * 13) % 60, 1 + (o.id * 29) % 60)
      -- Meia dúzia de referências nunca chega a vender-se. É o caso
      -- extremo do stock parado, e existe em qualquer catálogo real:
      -- comprou-se, ficou, e ninguém voltou a olhar.
      AND id % 13 <> 0
) p ON TRUE
WHERE o.status = 'delivered';

-- Recepções: a maioria dentro do prazo, e um fornecedor sistematicamente
-- atrasado. Um atraso isolado é ruído; um padrão é uma conversa.
INSERT INTO supply.receipts (supplier_id, product_id, promised_at, received_at, quantity)
SELECT
    p.supplier_id,
    p.id,
    (CURRENT_DATE - INTERVAL '12 months' + (g % 360) * INTERVAL '1 day')::DATE,
    CASE
        WHEN p.supplier_id = 7 THEN (CURRENT_DATE - INTERVAL '12 months' + (g % 360) * INTERVAL '1 day')::DATE + (9 + g % 12)
        WHEN g % 11 = 0 THEN (CURRENT_DATE - INTERVAL '12 months' + (g % 360) * INTERVAL '1 day')::DATE + (2 + g % 4)
        ELSE (CURRENT_DATE - INTERVAL '12 months' + (g % 360) * INTERVAL '1 day')::DATE
    END,
    50 + (g * 11) % 400
FROM generate_series(1, 400) g
JOIN catalog.products p ON p.id = 1 + (g * 3) % 60;

CREATE INDEX IF NOT EXISTS idx_ol_order ON sales.order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_ol_product ON sales.order_lines(product_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON sales.orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_stock_product ON inventory.stock(product_id);
CREATE INDEX IF NOT EXISTS idx_receipts_supplier ON supply.receipts(supplier_id);

COMMIT;
