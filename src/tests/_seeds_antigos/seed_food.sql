-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Alimentação Selecta e Vinhos
-- ─────────────────────────────────────────────────────────────────
-- Já existe um sector de Distribuição, e não chega para quem distribui
-- comida e vinho. O que distingue este negócio dos outros são três
-- coisas que o sector genérico não tem:
--
--   • a mercadoria morre. Tem lote e tem data, e o stock por
--     referência não sabe disso — só o stock por lote sabe;
--   • o preço não é o preço. O rappel acordado com o cliente só se
--     aplica depois, sobre o acumulado, e a margem que se celebrou em
--     Janeiro é outra em Dezembro;
--   • o vinho parado às vezes é guarda e às vezes é esquecimento, e os
--     dois parecem exactamente iguais numa folha de stock.
--
--   assortment.products      — referência, família, validade, se é de guarda
--   warehouse.lots           — o lote: quando entrou, quando caduca
--   warehouse.stock          — quanto resta de cada lote, e em que zona
--
-- Os lotes vivem no armazém e não no catálogo, de propósito: uma ligação
-- Postgres vê um esquema só, e é no armazém que se pergunta "o que é que
-- caduca nos próximos 60 dias e quantas unidades restam". Com os lotes no
-- catálogo, essa pergunta — a que mais vale aqui — ficava partida ao meio
-- entre duas ligações e nenhum agente lhe chegava.
--   trade.customers         — canal, praça, e o rappel acordado
--   trade.orders/order_lines — o que saiu, de que lote, e por quanto
--
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Sintéticos e gerados por fórmula. As praças são as da zona —
-- Badajoz, Mérida, Almendralejo, Zafra — porque é onde a conversa
-- acontece, não porque descrevam a operação de alguém.
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS assortment;
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS trade;

CREATE TABLE IF NOT EXISTS assortment.suppliers (
    id      SERIAL PRIMARY KEY,
    name    TEXT NOT NULL,
    region  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assortment.products (
    id              SERIAL PRIMARY KEY,
    sku             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    family          TEXT NOT NULL,
    supplier_id     INT NOT NULL REFERENCES assortment.suppliers(id),
    unit_cost       NUMERIC(10,2) NOT NULL,
    list_price      NUMERIC(10,2) NOT NULL,
    -- Dias de vida a partir da entrada. O vinho de guarda leva anos; o
    -- queijo fresco leva semanas. É a diferença que faz a pergunta.
    shelf_life_days INT NOT NULL,
    -- Verdadeiro quando parar é a estratégia e não o esquecimento.
    is_vintage      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS warehouse.lots (
    id          SERIAL PRIMARY KEY,
    product_id  INT NOT NULL REFERENCES assortment.products(id),
    lot_code    TEXT NOT NULL UNIQUE,
    received_on DATE NOT NULL,
    best_before DATE NOT NULL,
    quantity    INT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse.stock (
    id       SERIAL PRIMARY KEY,
    lot_id   INT NOT NULL REFERENCES warehouse.lots(id),
    quantity INT NOT NULL,
    zone     TEXT NOT NULL        -- seco | refrigerado | bodega
);

CREATE TABLE IF NOT EXISTS trade.customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    channel     TEXT NOT NULL,    -- restaurante | hotel | tienda | distribuidor
    city        TEXT NOT NULL,
    -- O rappel acordado, aplicado sobre o acumulado do ano. Não está em
    -- nenhuma linha de factura — está no contrato.
    rebate_pct  NUMERIC(5,4) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trade.orders (
    id          SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES trade.customers(id),
    ordered_at  DATE NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade.order_lines (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL REFERENCES trade.orders(id),
    lot_id     INT NOT NULL REFERENCES warehouse.lots(id),
    quantity   INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL,
    discount   NUMERIC(5,4) NOT NULL DEFAULT 0
);

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE trade.order_lines, trade.orders, trade.customers,
         warehouse.stock, warehouse.lots, assortment.products,
         assortment.suppliers
    RESTART IDENTITY CASCADE;

INSERT INTO assortment.suppliers (name, region)
SELECT
    (ARRAY['Bodegas Ribera Alta','Dehesa de Extremadura','Aceites del Guadiana',
           'Quesería Serena','Conservas del Cantábrico','Viñedos del Duero',
           'Ibéricos Montánchez','Cavas del Penedés'])[g],
    (ARRAY['Ribera del Duero','Extremadura','Extremadura','Extremadura',
           'Cantabria','Castilla y León','Extremadura','Cataluña'])[g]
FROM generate_series(1, 8) g;

-- 72 referências em 6 famílias. A validade é o que separa este negócio
-- de uma distribuição qualquer: o cava dura 3 anos, o queijo fresco
-- dura 40 dias, e o tinto de guarda não "dura" — envelhece.
INSERT INTO assortment.products
    (sku, name, family, supplier_id, unit_cost, list_price, shelf_life_days, is_vintage)
SELECT
    'REF-' || LPAD(g::TEXT, 4, '0'),
    fam.nome || ' ' || (ARRAY['Selección','Reserva','Gran Selección','Tradicional',
                              'Artesano','Origen'])[1 + g % 6] || ' ' || g,
    fam.nome,
    1 + g % 8,
    custo.c,
    -- Margem bruta de 28% a 52%, conforme a família. É sobre esta que o
    -- rappel vai morder mais à frente.
    (custo.c * (1.28 + ((g % 6) * 0.048)))::NUMERIC(10,2),
    fam.vida,
    fam.guarda
FROM generate_series(1, 72) g
CROSS JOIN LATERAL (
    SELECT
        (ARRAY['Vino tinto','Vino blanco','Cava','Aceite','Queso','Ibérico'])[1 + g % 6] AS nome,
        (ARRAY[2200, 900, 1100, 540, 45, 120])[1 + g % 6] AS vida,
        ((1 + g % 6) = 1) AS guarda
) fam
CROSS JOIN LATERAL (SELECT (3 + (g * 7) % 48)::NUMERIC(10,2) AS c) custo;

-- 5 lotes por referência, ao longo de 24 meses.
--
-- Três coisas plantadas de propósito:
--   • um bolso de lotes já caducado, ainda com existências — a conta
--     que não existe porque o stock se vê por referência e não por lote;
--   • outro bolso a caducar nos próximos 60 dias, que é o único que
--     ainda se consegue vender;
--   • o vinho de guarda fica parado de propósito, para separar o que
--     está parado por estratégia do que está parado por esquecimento.
INSERT INTO warehouse.lots (product_id, lot_code, received_on, best_before, quantity)
SELECT
    p.id,
    'L' || LPAD(p.id::TEXT, 4, '0') || '-' || g,
    entrada.d,
    (entrada.d + p.shelf_life_days)::DATE,
    40 + ABS(hashint4(p.id * 100 + g)) % 260
FROM assortment.products p
CROSS JOIN generate_series(1, 5) g
CROSS JOIN LATERAL (
    -- ⚠️ A janela de entrada acompanha a validade do produto.
    --
    -- A primeira versão espalhava todos os lotes por 24 meses, incluindo
    -- os de queijo fresco, que dura 120 dias. Resultado: 42% dos lotes
    -- apareciam caducados. É um número forte e é um número impossível —
    -- um distribuidor nesse estado estava fechado, e qualquer pessoa do
    -- ramo percebe isso antes de acabar a frase.
    --
    -- Ninguém guarda queijo de dois anos. A janela é 1,4× a validade,
    -- com um tecto de 700 dias para o vinho: as pontas vencidas passam
    -- a ser as que aparecem mesmo num armazém a funcionar.
    SELECT (CURRENT_DATE
            - (ABS(hashint4(p.id * 31 + g * 7))
               % LEAST((p.shelf_life_days * 1.4)::INT, 700)) * INTERVAL '1 day')::DATE AS d
) entrada;

-- O que resta de cada lote. A zona é consequência da família, como na
-- vida real: o vinho vai para a adega, o queijo para o frio.
INSERT INTO warehouse.stock (lot_id, quantity, zone)
SELECT
    l.id,
    -- Quase tudo escoou; o que fica são as pontas. Os lotes de guarda
    -- ficam praticamente intactos, que é o ponto.
    CASE
        WHEN p.is_vintage THEN (l.quantity * 0.85)::INT
        ELSE (l.quantity * (ABS(hashint4(l.id)) % 30) / 100.0)::INT
    END,
    CASE
        WHEN p.family IN ('Vino tinto', 'Vino blanco', 'Cava') THEN 'bodega'
        WHEN p.family IN ('Queso', 'Ibérico') THEN 'refrigerado'
        ELSE 'seco'
    END
FROM warehouse.lots l
JOIN assortment.products p ON p.id = l.product_id;

-- 90 clientes de hostelaria na praça. O rappel é o que vai comer a
-- margem depois: varia por canal e por volume, e não aparece em
-- nenhuma linha de factura.
INSERT INTO trade.customers (name, channel, city, rebate_pct)
SELECT
    -- ⚠️ O tipo no nome tem de concordar com o canal.
    --
    -- Os dois saíam de progressões independentes, e a lista de clientes
    -- mostrava «Cafetería San Juan (distribuidor)» e «Hostal El Olivar
    -- (distribuidor)». Para quem vende neste sector o canal é
    -- vocabulário diário: é a primeira linha que lê e a primeira
    -- incoerência que vê.
    --
    -- Três tipos por canal, escolhidos pelo mesmo `g` que já decide o
    -- resto, para a correspondência ser sempre a mesma.
    -- Os dois subscritos: o Postgres não corta uma linha de um array
    -- 2-D com um índice só.
    canal.tipos[1 + g % 4][1 + (g / 4) % 3]
        || ' ' || (ARRAY['El Mirador','La Dehesa','Puerta Palma','San Juan',
                         'Los Arcos','La Giralda','El Olivar','Las Cruces',
                         'Santa Marina','El Rincón'])[1 + (g / 10) % 10],
    canal.c,
    (ARRAY['Badajoz','Mérida','Almendralejo','Cáceres','Zafra','Don Benito',
           'Villanueva de la Serena','Sevilla'])[1 + g % 8],
    canal.rappel
FROM generate_series(1, 90) g
CROSS JOIN LATERAL (
    SELECT
        (ARRAY['restaurante','hotel','tienda','distribuidor'])[1 + g % 4] AS c,
        (ARRAY[
            ARRAY['Restaurante','Asador','Taberna'],
            ARRAY['Hotel','Hostal','Mesón'],
            ARRAY['Tienda','Bodega','Colmado'],
            ARRAY['Distribuciones','Mayorista','Suministros']
        ]) AS tipos,
        -- O distribuidor negoceia o dobro de toda a gente. É ele que faz
        -- a margem líquida divergir da bruta.
        (ARRAY[0.0300, 0.0450, 0.0150, 0.0900])[1 + g % 4]::NUMERIC(5,4) AS rappel
) canal;

INSERT INTO trade.orders (customer_id, ordered_at, status)
SELECT
    1 + (g * 17) % 90,
    (CURRENT_DATE - INTERVAL '18 months'
     + (ABS(hashint4(g)) % 540) * INTERVAL '1 day')::DATE,
    CASE WHEN g % 29 = 0 THEN 'cancelled' ELSE 'delivered' END
FROM generate_series(1, 2400) g;

-- Linhas: 1 a 3 por encomenda, sempre de um lote concreto. É o lote na
-- linha que permite responder "de que lote é que isto saiu" — e sem
-- essa coluna a pergunta da caducidade não tem resposta nenhuma.
INSERT INTO trade.order_lines (order_id, lot_id, quantity, unit_price, discount)
SELECT
    o.id,
    l.id,
    1 + ABS(hashint4(o.id * 13 + l.id)) % 24,
    p.list_price,
    -- O desconto de linha é pequeno; é o rappel do contrato que faz o
    -- estrago, e esse não está aqui.
    (ABS(hashint4(o.id + l.id)) % 6) * 0.01
FROM trade.orders o
CROSS JOIN LATERAL (
    SELECT lo.id FROM warehouse.lots lo
    WHERE lo.id IN (
        1 + ABS(hashint4(o.id * 7)) % 360,
        1 + ABS(hashint4(o.id * 23)) % 360,
        1 + ABS(hashint4(o.id * 41)) % 360
    )
    -- Quatro referências nunca chegam a vender-se. Acontece em qualquer
    -- catálogo: trouxe-se para um cliente que entretanto fechou, ficou
    -- em armazém, e ninguém voltou a olhar. É o caso extremo do capital
    -- parado, e sem ele o cartão "referências sem uma única venda"
    -- mostrava zero — um zero num painel é espaço morto.
    AND lo.product_id % 17 <> 0
) l
JOIN assortment.products p ON p.id = (SELECT product_id FROM warehouse.lots WHERE id = l.id)
WHERE o.status = 'delivered';

CREATE INDEX IF NOT EXISTS idx_lots_product ON warehouse.lots(product_id);
CREATE INDEX IF NOT EXISTS idx_lots_bb ON warehouse.lots(best_before);
CREATE INDEX IF NOT EXISTS idx_stock_lot ON warehouse.stock(lot_id);
CREATE INDEX IF NOT EXISTS idx_ol_order ON trade.order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_ol_lot ON trade.order_lines(lot_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON trade.orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON trade.orders(ordered_at);

COMMIT;
