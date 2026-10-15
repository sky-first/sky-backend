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
--   assortment.suppliers     — quem fornece, e de onde
--   assortment.products      — referência, família, validade, se é de guarda
--   warehouse.lots           — o lote: quando entrou, quando caduca, a que custo
--   warehouse.stock          — quanto resta de cada lote, e em que zona
--   trade.customers          — canal, praça, e o rappel acordado
--   trade.orders/order_lines — o que saiu, de que lote, por quanto e a que custo
--
-- Os lotes vivem no armazém e não no catálogo, de propósito: uma ligação
-- Postgres vê um esquema só, e é no armazém que se pergunta "o que é que
-- caduca nos próximos 60 dias e quantas unidades restam".
--
-- ── Porque é que isto foi reescrito (15/10/2026) ─────────────────
--
-- A primeira versão saía de `g % 6` e `g % 8`. A bateria de perguntas
-- de 14/10 em produção mostrou o preço disso, em vídeo:
--
--   • as 6 famílias com EXACTAMENTE o mesmo valor vendido;
--   • os 8 fornecedores com 9 referências cada um;
--   • «0 € de vinho de guarda», porque o custo só existia no catálogo;
--   • «margem efectiva de 88,51 %», porque a linha não tinha custo e o
--     motor dividiu preço por preço.
--
-- Agora cada referência é escrita à mão (nome, custo, validade, peso
-- nas vendas), cada cliente tem um tamanho tirado de uma cauda longa, e
-- as encomendas seguem o calendário: segunda-feira forte, domingo vazio,
-- Dezembro de espumante e ibérico, Verão de branco.
--
-- ── Aleatório, mas sempre o mesmo ────────────────────────────────
--
-- Nada de random(): a ordem de chamada depende do plano de execução e
-- dois carregamentos davam números diferentes. `pg_temp.u(...)` é um
-- hash dos argumentos — a mesma chave dá sempre o mesmo número, em
-- qualquer carga. As funções vivem em `pg_temp` e morrem com a sessão:
-- não fica nada na base.
--
-- As datas contam a partir de CURRENT_DATE. O Job volta a carregar
-- todos os dias, por isso "o último mês" e "esta semana" têm sempre
-- dados — mas nunca dados do futuro.
--
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Sintéticos. As praças são as da zona — Badajoz, Mérida, Almendralejo,
-- Zafra — porque é onde a conversa acontece, não porque descrevam a
-- operação de alguém.
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
    zone     TEXT NOT NULL        -- seco | refrigerado | bodega | bodega de guarda
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

-- ── Colunas acrescentadas a 15/10/2026 ───────────────────────────
--
-- `CREATE TABLE IF NOT EXISTS` não mexe numa tabela que já existe, e a
-- `skydemo` de produção tem-nas todas. Sem o ALTER as colunas novas só
-- apareciam numa base vazia — ou seja, em nenhum sítio que importe.
--
-- O custo do lote e o custo na linha são o custo da referência no
-- momento. Estão repetidos de propósito, como num ERP a sério: o
-- armazém valoriza o stock sem perguntar ao catálogo, e o comercial
-- calcula a margem sem perguntar a ninguém. Uma ligação vê um esquema
-- só, e era essa a razão das duas respostas erradas da bateria.
ALTER TABLE warehouse.lots      ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(10,2) NOT NULL DEFAULT 0;
ALTER TABLE trade.order_lines   ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(10,2) NOT NULL DEFAULT 0;

-- ── o gerador ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION pg_temp.u(VARIADIC k INT[]) RETURNS FLOAT8
LANGUAGE sql IMMUTABLE AS $$
    SELECT (hashtext('alimentacion:' || array_to_string(k, ':')) & 2147483647)::FLOAT8
           / 2147483648.0
$$;

-- Normal(0,1) por Box-Muller, para os tamanhos com cauda (log-normal).
CREATE OR REPLACE FUNCTION pg_temp.z(VARIADIC k INT[]) RETURNS FLOAT8
LANGUAGE sql IMMUTABLE AS $$
    SELECT sqrt(-2 * ln(GREATEST(pg_temp.u(VARIADIC k || 1), 1e-9)))
           * cos(2 * pi() * pg_temp.u(VARIADIC k || 2))
$$;

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE trade.order_lines, trade.orders, trade.customers,
         warehouse.stock, warehouse.lots, assortment.products,
         assortment.suppliers
    RESTART IDENTITY CASCADE;

-- Oito fornecedores com catálogos de tamanhos diferentes — de 6 a 13
-- referências. Um distribuidor real tem a adega principal com metade da
-- carta de tintos e o queijeiro com uma dúzia; ninguém tem nove de cada.
INSERT INTO assortment.suppliers (id, name, region) VALUES
    (1, 'Bodegas Ribera Alta',      'Ribera del Duero'),
    (2, 'Dehesa de Extremadura',    'Extremadura'),
    (3, 'Aceites del Guadiana',     'Extremadura'),
    (4, 'Quesería Serena',          'Extremadura'),
    (5, 'Bodegas Tierra de Barros', 'Extremadura'),
    (6, 'Viñedos del Duero',        'Castilla y León'),
    (7, 'Ibéricos Montánchez',      'Extremadura'),
    (8, 'Cavas del Penedés',        'Cataluña');
SELECT setval('assortment.suppliers_id_seq', 8);

-- 72 referências escritas à mão. As colunas a mais servem só o gerador:
--   peso    — quanto vende, relativo às outras (0 = nunca vendeu);
--   uds     — unidades típicas numa linha (uma garrafa vai à caixa de 6
--             ou 12; um presunto vai à peça).
-- As quatro de peso 0 são o caso extremo do capital parado: trouxeram-se
-- para um cliente que entretanto fechou, ficaram, e ninguém voltou a
-- olhar. Sem elas o cartão "referências sem uma única venda" dava zero.
CREATE TEMP TABLE _ref ON COMMIT DROP AS
SELECT ROW_NUMBER() OVER () AS id, r.*
FROM (VALUES
    -- Vino tinto: 18, dos quais 8 de guarda
    ('Vino tinto', 1, 'Ribera Alta Joven',                    3.90, 1095, FALSE, 1.60, 36),
    ('Vino tinto', 1, 'Ribera Alta Roble',                    5.20, 1460, FALSE, 1.90, 36),
    ('Vino tinto', 1, 'Ribera Alta Crianza',                  7.80, 1460, FALSE, 2.70, 36),
    ('Vino tinto', 1, 'Ribera Alta Reserva',                 13.50, 3650, TRUE,  1.10, 24),
    ('Vino tinto', 1, 'Ribera Alta Gran Reserva',            24.00, 3650, TRUE,  0.45, 12),
    ('Vino tinto', 1, 'Ribera Alta Viñas Viejas',            18.50, 3650, TRUE,  0.50, 12),
    ('Vino tinto', 1, 'Ribera Alta Pago Valdehierro',        32.00, 3650, TRUE,  0.22, 6),
    ('Vino tinto', 1, 'Ribera Alta Crianza Magnum',          17.00, 1460, FALSE, 0.00, 6),
    ('Vino tinto', 1, 'Ribera Alta Reserva Especial',        21.00, 3650, TRUE,  0.35, 12),
    ('Vino tinto', 1, 'Ribera Alta Tinto Fino',               6.10, 1460, FALSE, 1.20, 36),
    ('Vino tinto', 1, 'Ribera Alta Selección de Barricas',   27.50, 3650, TRUE,  0.20, 6),
    ('Vino tinto', 1, 'Ribera Alta Cosecha',                  4.60, 1095, FALSE, 1.40, 36),
    ('Vino tinto', 1, 'Ribera Alta Edición Limitada',        38.00, 3650, TRUE,  0.12, 6),
    ('Vino tinto', 6, 'Viñedos del Duero Toro Crianza',       8.40, 1460, FALSE, 0.90, 24),
    ('Vino tinto', 6, 'Viñedos del Duero Toro Reserva',      14.20, 3650, TRUE,  0.50, 12),
    ('Vino tinto', 6, 'Viñedos del Duero Cigales Joven',      3.60, 1095, FALSE, 0.70, 36),
    ('Vino tinto', 5, 'Tierra de Barros Tempranillo',         3.10, 1095, FALSE, 2.30, 48),
    ('Vino tinto', 5, 'Tierra de Barros Garnacha Tintorera',  4.40, 1095, FALSE, 0.80, 36),
    -- Vino blanco: 12
    ('Vino blanco', 6, 'Viñedos del Duero Rueda Verdejo',     3.80,  730, FALSE, 2.40, 48),
    ('Vino blanco', 6, 'Viñedos del Duero Verdejo sobre Lías', 5.40, 730, FALSE, 1.00, 36),
    ('Vino blanco', 6, 'Viñedos del Duero Sauvignon Blanc',   4.90,  730, FALSE, 0.80, 36),
    ('Vino blanco', 6, 'Viñedos del Duero Verdejo Barrica',   8.90, 1095, FALSE, 0.35, 12),
    ('Vino blanco', 6, 'Viñedos del Duero Viura',             3.20,  730, FALSE, 0.60, 36),
    ('Vino blanco', 5, 'Tierra de Barros Cayetana',           2.70,  730, FALSE, 1.50, 48),
    ('Vino blanco', 5, 'Tierra de Barros Pardina',            2.90,  730, FALSE, 1.10, 48),
    ('Vino blanco', 5, 'Tierra de Barros Macabeo',            3.10,  730, FALSE, 0.70, 36),
    ('Vino blanco', 5, 'Tierra de Barros Chardonnay',         4.60,  730, FALSE, 0.50, 24),
    ('Vino blanco', 5, 'Tierra de Barros Eva de los Santos',  3.40,  730, FALSE, 0.40, 24),
    ('Vino blanco', 5, 'Tierra de Barros Blanco Joven',       2.40,  550, FALSE, 1.80, 48),
    ('Vino blanco', 5, 'Tierra de Barros Moscatel',           5.10,  730, FALSE, 0.25, 12),
    -- Cava: 8 (Almendralejo também é D.O. Cava)
    ('Cava', 5, 'Cava de Almendralejo Brut',                  3.90, 1095, FALSE, 1.30, 36),
    ('Cava', 8, 'Cavas del Penedés Brut Nature',              5.60, 1095, FALSE, 1.60, 36),
    ('Cava', 8, 'Cavas del Penedés Brut Reserva',             6.80, 1095, FALSE, 1.10, 36),
    ('Cava', 8, 'Cavas del Penedés Rosado',                   6.20, 1095, FALSE, 0.60, 24),
    ('Cava', 8, 'Cavas del Penedés Gran Reserva',            13.80, 1460, FALSE, 0.30, 12),
    ('Cava', 8, 'Cavas del Penedés Semiseco',                 4.80, 1095, FALSE, 0.50, 24),
    ('Cava', 8, 'Cavas del Penedés Brut Magnum',             14.50, 1095, FALSE, 0.15, 6),
    ('Cava', 8, 'Cavas del Penedés Reserva de la Familia',   10.20, 1460, FALSE, 0.35, 12),
    -- Aceite: 10
    ('Aceite', 3, 'AOVE Guadiana Picual 500 ml',              4.10,  540, FALSE, 1.80, 24),
    ('Aceite', 3, 'AOVE Guadiana Picual 5 l',                29.50,  540, FALSE, 1.20, 6),
    ('Aceite', 3, 'AOVE Guadiana Arbequina 500 ml',           4.60,  540, FALSE, 1.00, 24),
    ('Aceite', 3, 'AOVE Guadiana Cornicabra 750 ml',          5.80,  540, FALSE, 0.60, 24),
    ('Aceite', 3, 'AOVE Guadiana Manzanilla Cacereña 500 ml', 5.20,  540, FALSE, 0.50, 24),
    ('Aceite', 3, 'AOVE Guadiana Cosecha Temprana 500 ml',    8.40,  450, FALSE, 0.30, 12),
    ('Aceite', 3, 'AOVE Guadiana Verdial 500 ml',             4.90,  540, FALSE, 0.30, 12),
    ('Aceite', 3, 'Aceite de Oliva Guadiana Suave 1 l',       4.70,  540, FALSE, 1.40, 24),
    ('Aceite', 3, 'AOVE Guadiana Monodosis (caja 100)',      11.20,  540, FALSE, 0.00, 6),
    ('Aceite', 2, 'AOVE Dehesa Gata-Hurdes 500 ml',           6.30,  540, FALSE, 0.25, 12),
    -- Queso: 13
    ('Queso', 4, 'Torta de la Serena DOP 500 g',              8.60,   90, FALSE, 2.00, 12),
    ('Queso', 4, 'Torta de la Serena DOP 1 kg',              15.40,   90, FALSE, 1.00, 6),
    ('Queso', 4, 'Queso de la Serena Curado 1 kg',           13.20,  240, FALSE, 1.10, 6),
    ('Queso', 4, 'Queso de la Serena Semicurado 1 kg',       11.80,  180, FALSE, 0.90, 6),
    ('Queso', 4, 'Queso de Oveja Añejo 1 kg',                16.50,  300, FALSE, 0.50, 6),
    ('Queso', 4, 'Queso de Cabra Fresco 500 g',               4.10,   30, FALSE, 1.20, 12),
    ('Queso', 4, 'Queso de Cabra al Pimentón 500 g',          6.40,  150, FALSE, 0.60, 12),
    ('Queso', 4, 'Queso de Oveja en Aceite 750 g',           10.90,  365, FALSE, 0.35, 6),
    ('Queso', 4, 'Torta Cremosa Mini 250 g',                  4.80,   75, FALSE, 0.80, 12),
    ('Queso', 4, 'Queso de Mezcla Tierno 1 kg',               8.20,  120, FALSE, 0.70, 6),
    ('Queso', 4, 'Queso Ibores DOP 1 kg',                    12.60,  200, FALSE, 0.40, 6),
    ('Queso', 4, 'Rulo de Cabra 1 kg',                        7.30,   45, FALSE, 0.00, 6),
    ('Queso', 2, 'Torta del Casar DOP 500 g',                10.40,   90, FALSE, 0.70, 12),
    -- Ibérico: 11
    ('Ibérico', 2, 'Jamón Ibérico de Bellota 50 % (pieza)', 245.00,  540, FALSE, 0.30, 2),
    ('Ibérico', 2, 'Paleta Ibérica de Bellota (pieza)',     118.00,  450, FALSE, 0.35, 2),
    ('Ibérico', 2, 'Lomo Ibérico de Bellota 1 kg',           38.00,  240, FALSE, 0.50, 4),
    ('Ibérico', 2, 'Chorizo Ibérico de Bellota 1 kg',        14.50,  240, FALSE, 0.80, 6),
    ('Ibérico', 2, 'Salchichón Ibérico de Bellota 1 kg',     15.20,  240, FALSE, 0.60, 6),
    ('Ibérico', 7, 'Jamón Ibérico de Cebo (pieza)',         142.00,  450, FALSE, 0.50, 2),
    ('Ibérico', 7, 'Paleta Ibérica de Cebo (pieza)',         68.00,  365, FALSE, 0.60, 2),
    ('Ibérico', 7, 'Jamón Ibérico Loncheado 100 g',           4.90,  120, FALSE, 2.20, 24),
    ('Ibérico', 7, 'Lomo Ibérico Loncheado 100 g',            4.40,  120, FALSE, 1.30, 24),
    ('Ibérico', 7, 'Morcón Ibérico 1 kg',                    13.00,  240, FALSE, 0.00, 6),
    ('Ibérico', 7, 'Presa Ibérica Curada 1 kg',              22.00,  240, FALSE, 0.30, 4)
) AS r(family, supplier_id, name, cost, vida, guarda, peso, uds);

-- O preço de tarifa: a margem de tarifa muda com a família (o aceite
-- vive de volume, o vinho de guarda vende-se caro) e, dentro dela, de
-- referência para referência — o agente "Margen de tarifa por familia"
-- tem de ter alguma coisa para encontrar.
INSERT INTO assortment.products
    (id, sku, name, family, supplier_id, unit_cost, list_price, shelf_life_days, is_vintage)
SELECT
    r.id,
    'REF-' || LPAD(r.id::TEXT, 4, '0'),
    r.name,
    r.family,
    r.supplier_id,
    r.cost,
    ROUND((r.cost * (
        CASE
            WHEN r.guarda                THEN 1.62
            WHEN r.family = 'Vino tinto' THEN 1.42
            WHEN r.family = 'Vino blanco' THEN 1.38
            WHEN r.family = 'Cava'       THEN 1.45
            WHEN r.family = 'Aceite'     THEN 1.24
            WHEN r.family = 'Queso'      THEN 1.40
            ELSE 1.30                                  -- Ibérico
        END
        + 0.05 * pg_temp.z(r.id::INT, 11)))::NUMERIC, 2),
    r.vida,
    r.guarda
FROM _ref r
ORDER BY r.id;
SELECT setval('assortment.products_id_seq', 72);

-- ── Os clientes ──────────────────────────────────────────────────
--
-- 90 clientes de hostelaria e retalho. O tamanho sai de uma log-normal:
-- meia dúzia muito grandes, a maioria pequenos, como em qualquer
-- carteira. O distribuidor compra em média o dobro e meio, e negoceia
-- o rappel mais alto e um preço um pouco abaixo da tarifa.
--
-- ⚠️ A diferença entre canais tem de estar sobretudo no RAPPEL e não no
-- preço. A página "Margen real" diz que o bruto é quase igual em todos
-- os canais e que o líquido não é — com o desconto todo no preço, o
-- bruto do distribuidor caía dez pontos e a página desmentia-se. Assim
-- fica: distribuidor < hotel < restaurante < tienda no líquido, com o
-- bruto a variar uns cinco pontos e o líquido o dobro disso.
--
-- O nome: 30 lugares × 3 blocos. Dentro de um canal, cada bloco tem o
-- seu tipo (Restaurante / Asador / Taberna…), por isso nenhum par
-- tipo+lugar se repete.
CREATE TEMP TABLE _cli ON COMMIT DROP AS
SELECT
    g AS id,
    canal.c AS channel,
    canal.i AS ci,
    -- Tamanho relativo (cauda longa).
    exp(0.85 * pg_temp.z(g, 21)) * (ARRAY[1.0, 0.9, 0.55, 2.5])[canal.i] AS tam,
    -- Preço negociado, relativo à tarifa.
    (ARRAY[0.985, 0.975, 1.00, 0.94])[canal.i] + 0.008 * pg_temp.z(g, 22) AS preco,
    -- 15 % entraram a meio do período; 8 % estão a ir-se embora.
    CASE WHEN pg_temp.u(g, 23) < 0.15 THEN (pg_temp.u(g, 24) * 420)::INT ELSE 0 END AS entra_dia,
    pg_temp.u(g, 25) < 0.08 AS sai,
    (ARRAY['Badajoz','Badajoz','Badajoz','Mérida','Mérida','Cáceres','Cáceres',
           'Almendralejo','Almendralejo','Zafra','Don Benito','Don Benito',
           'Villanueva de la Serena','Sevilla','Sevilla','Sevilla'])
        [1 + (pg_temp.u(g, 26) * 16)::INT % 16] AS city
FROM generate_series(1, 90) g
CROSS JOIN LATERAL (
    SELECT CASE
               WHEN pg_temp.u(g, 20) < 0.44 THEN 'restaurante'
               WHEN pg_temp.u(g, 20) < 0.64 THEN 'hotel'
               WHEN pg_temp.u(g, 20) < 0.89 THEN 'tienda'
               ELSE 'distribuidor'
           END AS c,
           CASE
               WHEN pg_temp.u(g, 20) < 0.44 THEN 1
               WHEN pg_temp.u(g, 20) < 0.64 THEN 2
               WHEN pg_temp.u(g, 20) < 0.89 THEN 3
               ELSE 4
           END AS i
) canal;

INSERT INTO trade.customers (id, name, channel, city, rebate_pct)
SELECT
    c.id,
    (ARRAY[
        ARRAY['Restaurante','Asador','Taberna'],
        ARRAY['Hotel','Hostal','Mesón'],
        ARRAY['Tienda','Bodega','Colmado'],
        ARRAY['Distribuciones','Mayorista','Suministros']
    ])[c.ci][1 + (c.id - 1) / 30]
        || ' ' ||
    (ARRAY['El Mirador','La Dehesa','Puerta Palma','San Juan','Los Arcos',
           'La Giralda','El Olivar','Las Cruces','Santa Marina','El Rincón',
           'La Alcazaba','El Pilar','San Francisco','Los Naranjos','La Encina',
           'El Puente','Santa Eulalia','La Plaza','Los Molinos','El Guadiana',
           'La Muralla','San Roque','El Casino','La Fuente','Los Alcores',
           'El Templo','La Vega','San Lázaro','El Albarregas','La Marina'])[1 + (c.id - 1) % 30],
    c.channel,
    c.city,
    -- O rappel cresce com o volume dentro do canal: quem compra mais
    -- negociou mais. Varia por cliente, não é um número por canal.
    ROUND(LEAST(0.095, GREATEST(0,
        (ARRAY[0.022, 0.033, 0.004, 0.068])[c.ci]
        + (ARRAY[0.006, 0.007, 0.003, 0.012])[c.ci] * LN(GREATEST(c.tam, 0.05) /
              (ARRAY[1.0, 0.9, 0.55, 2.5])[c.ci])
        + 0.003 * pg_temp.z(c.id, 27))))::NUMERIC, 4)
FROM _cli c
ORDER BY c.id;
SELECT setval('trade.customers_id_seq', 90);

-- ── As encomendas ────────────────────────────────────────────────
--
-- 18 meses, dia a dia, cliente a cliente: há encomenda nesse dia com uma
-- probabilidade que junta o tamanho do cliente, o dia da semana
-- (segunda é o dia de repor a cozinha; domingo não se entrega), o mês
-- (Dezembro é o mês do ano; Janeiro paga-o) e uma tendência ligeira de
-- crescimento. Quem está a sair cai para um quarto nos últimos 90 dias.
CREATE TEMP TABLE _enc ON COMMIT DROP AS
SELECT
    ROW_NUMBER() OVER (ORDER BY dia.d DESC, c.id) AS id,
    c.id AS customer_id,
    (CURRENT_DATE - dia.d) AS ordered_at
FROM _cli c
CROSS JOIN generate_series(0, 547) AS dia(d)
WHERE (547 - dia.d) >= c.entra_dia
  AND pg_temp.u(c.id, dia.d, 30) <
      LEAST(0.95,
          -- encomendas por semana, conforme o canal
          (ARRAY[0.95, 0.85, 0.45, 1.45])[c.ci] * LEAST(c.tam, 4.0) / 6.0
          * (ARRAY[0.00, 1.45, 1.15, 1.00, 1.20, 0.95, 0.25])
              [1 + EXTRACT(DOW FROM CURRENT_DATE - dia.d)::INT]
          * (ARRAY[0.80, 0.82, 0.92, 1.00, 1.05, 1.10, 1.15, 1.10, 1.00, 0.98, 1.08, 1.30])
              [EXTRACT(MONTH FROM CURRENT_DATE - dia.d)::INT]
          * (1 + 0.10 * (547 - dia.d) / 547.0)
          * CASE WHEN c.sai AND dia.d < 90 THEN 0.25 ELSE 1 END);

INSERT INTO trade.orders (id, customer_id, ordered_at, status)
SELECT
    e.id,
    e.customer_id,
    e.ordered_at,
    -- ~3 % anuladas. Ficam sem linhas: não saiu nada do armazém.
    CASE WHEN pg_temp.u(e.id::INT, 31) < 0.03 THEN 'cancelled' ELSE 'delivered' END
FROM _enc e
ORDER BY e.id;
SELECT setval('trade.orders_id_seq', (SELECT MAX(id) FROM trade.orders));

-- ── Os lotes ─────────────────────────────────────────────────────
--
-- 360 lotes, como antes — mas já não 5 por referência. O queijo fresco
-- entra todos os meses e o tinto duas vezes por ano: 10 lotes para o
-- que vive menos de 120 dias, 6 até um ano, 4 ou 5 para o resto (5 para
-- as doze que mais vendem). A soma dá 360.
--
-- O primeiro lote de cada referência entrou antes da primeira encomenda
-- do período e o último há poucos dias: a linha da encomenda aponta
-- sempre para o lote que estava em armazém nesse dia. O vinho de guarda
-- entra mais cedo — envelhece cá dentro.
CREATE TEMP TABLE _lot ON COMMIT DROP AS
WITH n AS (
    SELECT r.id, r.vida, r.guarda,
           CASE
               WHEN r.vida < 120 THEN 10
               WHEN r.vida < 365 THEN 6
               WHEN ROW_NUMBER() OVER (
                        PARTITION BY (r.vida >= 365)
                        ORDER BY r.peso DESC, r.id) <= 12 THEN 5
               ELSE 4
           END AS nl
    FROM _ref r
)
SELECT
    ROW_NUMBER() OVER (ORDER BY n.id, k) AS id,
    n.id AS product_id,
    k,
    n.nl,
    (CURRENT_DATE
        - (CASE WHEN n.guarda THEN 160 ELSE 0 END)
        - ((n.nl - k) * 560.0 / (n.nl - 1))::INT
        - (3 + pg_temp.u(n.id::INT, k::INT, 40) * 12)::INT) AS received_on
FROM n
CROSS JOIN LATERAL generate_series(1, n.nl) AS k;

-- A quantidade do lote só se sabe depois das vendas (é o que se vendeu
-- dele mais o que resta). Entra a zero e é corrigida mais abaixo.
INSERT INTO warehouse.lots (id, product_id, lot_code, received_on, best_before, quantity, unit_cost)
SELECT
    l.id,
    l.product_id,
    'L' || TO_CHAR(l.received_on, 'YYMM') || '-' || LPAD(l.product_id::TEXT, 3, '0')
        || '-' || l.k,
    l.received_on,
    l.received_on + r.vida,
    0,
    r.cost
FROM _lot l
JOIN _ref r ON r.id = l.product_id
ORDER BY l.id;
SELECT setval('warehouse.lots_id_seq', (SELECT MAX(id) FROM warehouse.lots));

-- ── As linhas ────────────────────────────────────────────────────
--
-- Cada encomenda tenta entre 2 e 9 linhas (o distribuidor enche o
-- camião; a tienda leva o que falta). Cada tentativa escolhe uma
-- referência pelo seu peso nas vendas, corrigido pela estação da
-- família e pelo gosto do canal: o espumante e o ibérico disparam em
-- Dezembro, o branco no Verão, a tienda vende mais aceite e ibérico, o
-- hotel mais espumante. Referências repetidas na mesma encomenda
-- fundem-se — ninguém escreve a mesma linha duas vezes.
CREATE TEMP TABLE _cum ON COMMIT DROP AS
WITH w AS (
    SELECT m.mes, ch.ci, r.id AS ref_id,
           r.peso
           * (CASE r.family
                 WHEN 'Vino tinto'  THEN (ARRAY[0.85,0.85,0.90,0.95,0.95,0.85,0.80,0.80,1.00,1.10,1.25,1.60])[m.mes]
                 WHEN 'Vino blanco' THEN (ARRAY[0.70,0.75,0.90,1.05,1.20,1.35,1.50,1.45,1.10,0.90,0.85,1.00])[m.mes]
                 WHEN 'Cava'        THEN (ARRAY[0.60,0.60,0.70,0.80,0.95,1.10,1.10,1.00,0.80,0.80,1.30,2.60])[m.mes]
                 WHEN 'Aceite'      THEN (ARRAY[1.10,1.00,1.00,1.00,0.95,0.90,0.85,0.85,0.95,1.05,1.15,1.20])[m.mes]
                 WHEN 'Queso'       THEN (ARRAY[0.90,0.90,1.00,1.05,1.05,1.00,0.95,0.90,1.00,1.05,1.15,1.40])[m.mes]
                 ELSE                    (ARRAY[0.80,0.75,0.85,0.90,0.90,0.85,0.80,0.80,0.95,1.05,1.40,2.20])[m.mes]
              END)
           -- restaurante | hotel | tienda | distribuidor
           * (CASE r.family
                 WHEN 'Vino tinto'  THEN (ARRAY[1.30, 1.00, 0.80, 1.00])[ch.ci]
                 WHEN 'Vino blanco' THEN (ARRAY[1.00, 1.30, 0.70, 1.00])[ch.ci]
                 WHEN 'Cava'        THEN (ARRAY[0.80, 1.60, 1.00, 1.00])[ch.ci]
                 WHEN 'Aceite'      THEN (ARRAY[0.90, 0.80, 1.60, 1.20])[ch.ci]
                 WHEN 'Queso'       THEN (ARRAY[1.20, 0.90, 1.20, 0.90])[ch.ci]
                 ELSE                    (ARRAY[0.90, 0.90, 1.50, 1.10])[ch.ci]
              END) AS w
    FROM generate_series(1, 12) AS m(mes)
    CROSS JOIN generate_series(1, 4) AS ch(ci)
    CROSS JOIN _ref r
    WHERE r.peso > 0
)
SELECT mes, ci, ref_id,
       COALESCE(SUM(w) OVER (PARTITION BY mes, ci ORDER BY ref_id
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
           / SUM(w) OVER (PARTITION BY mes, ci) AS lo,
       SUM(w) OVER (PARTITION BY mes, ci ORDER BY ref_id)
           / SUM(w) OVER (PARTITION BY mes, ci) AS hi
FROM w;

CREATE TEMP TABLE _lin ON COMMIT DROP AS
SELECT DISTINCT ON (o.id, cu.ref_id)
    o.id AS order_id,
    o.ordered_at,
    c.id AS customer_id,
    c.ci,
    c.preco,
    cu.ref_id,
    tentativa.t
FROM trade.orders o
JOIN _cli c ON c.id = o.customer_id
CROSS JOIN LATERAL generate_series(
    1, (ARRAY[2, 2, 1, 4])[c.ci] + (pg_temp.u(o.id, 50) * (ARRAY[5, 5, 4, 6])[c.ci])::INT
) AS tentativa(t)
JOIN _cum cu
  ON cu.mes = EXTRACT(MONTH FROM o.ordered_at)::INT
 AND cu.ci = c.ci
 AND pg_temp.u(o.id, tentativa.t, 51) >= cu.lo
 AND pg_temp.u(o.id, tentativa.t, 51) <  cu.hi
WHERE o.status = 'delivered'
ORDER BY o.id, cu.ref_id, tentativa.t;

INSERT INTO trade.order_lines (order_id, lot_id, quantity, unit_price, discount, unit_cost)
SELECT
    li.order_id,
    -- O lote que estava em armazém nesse dia: o último a entrar antes da
    -- encomenda.
    (SELECT l.id FROM _lot l
      WHERE l.product_id = li.ref_id AND l.received_on <= li.ordered_at
      ORDER BY l.received_on DESC LIMIT 1),
    -- Unidades: a maior parte das linhas é pequena, algumas enchem a
    -- palete. O distribuidor leva mais por linha, a tienda menos.
    GREATEST(1, ROUND(r.uds * (ARRAY[0.55, 0.65, 0.35, 1.30])[li.ci]
                      * power(pg_temp.u(li.order_id, li.ref_id::INT, 52), 1.6)
                      + pg_temp.u(li.order_id, li.ref_id::INT, 53)))::INT,
    -- O preço é o negociado com o cliente, não a tarifa.
    ROUND((p.list_price * li.preco)::NUMERIC, 2),
    -- Desconto de linha: promoções pontuais. O que come a margem é o
    -- rappel, e esse não está aqui.
    CASE
        WHEN pg_temp.u(li.order_id, li.ref_id::INT, 54) <
             (ARRAY[0.20, 0.22, 0.10, 0.40])[li.ci]
        THEN (ARRAY[0.02, 0.03, 0.05])[1 + (pg_temp.u(li.order_id, li.ref_id::INT, 55) * 3)::INT % 3]
        ELSE 0
    END,
    p.unit_cost
FROM _lin li
JOIN _ref r ON r.id = li.ref_id
JOIN assortment.products p ON p.id = li.ref_id
ORDER BY li.order_id, li.ref_id;

-- ── O que resta em cada lote ─────────────────────────────────────
--
-- Comprou-se o que se previa vender, com folga:
--   • lotes antigos: vendeu-se quase tudo; o que fica são as pontas
--     (0–12 %). Nos perecíveis, essas pontas já estão caducadas — é a
--     conta que não existe, porque o stock se vê por referência;
--   • o último lote: entrou há dias e está quase inteiro;
--   • o vinho de guarda: compra-se a mais de propósito, e fica;
--   • uma dúzia de lotes "esquecidos": entraram há meses e continuam
--     quase completos. É o que o agente "Existencias sin salida" procura;
--   • as quatro referências que nunca venderam: o lote inteiro.
CREATE TEMP TABLE _vend ON COMMIT DROP AS
SELECT l.id AS lot_id, l.product_id, l.k, l.nl,
       COALESCE((SELECT SUM(ol.quantity) FROM trade.order_lines ol WHERE ol.lot_id = l.id), 0) AS vendido
FROM _lot l;

CREATE TEMP TABLE _resta ON COMMIT DROP AS
SELECT
    v.lot_id,
    v.vendido,
    CASE
        WHEN r.peso = 0
            THEN 24 + (pg_temp.u(v.lot_id::INT, 60) * 96)::INT
        WHEN r.guarda
            THEN (v.vendido * (0.6 + 1.4 * pg_temp.u(v.lot_id::INT, 61)) + 36)::INT
        WHEN v.k = v.nl
            -- O último lote: a procura média de um lote anterior, quase
            -- toda ainda por vender.
            THEN GREATEST(6, (
                    (SELECT AVG(v2.vendido) FROM _vend v2
                      WHERE v2.product_id = v.product_id AND v2.k < v2.nl)
                    * (0.85 + 0.45 * pg_temp.u(v.lot_id::INT, 62)) - v.vendido)::INT)
        WHEN pg_temp.u(v.lot_id::INT, 63) < 0.035
            THEN (v.vendido * (0.6 + pg_temp.u(v.lot_id::INT, 64)) + 30)::INT
        ELSE (v.vendido * 0.12 * power(pg_temp.u(v.lot_id::INT, 65), 1.5))::INT
    END AS resta
FROM _vend v
JOIN _ref r ON r.id = v.product_id;

UPDATE warehouse.lots l
SET quantity = GREATEST(1, x.vendido + x.resta)
FROM _resta x
WHERE x.lot_id = l.id;

-- A zona é consequência da família, como na vida real: o vinho vai para
-- a adega, o queijo para o frio. O vinho de guarda tem a sua própria
-- adega — e é por isso que o armazém, sozinho, consegue dizer quanto
-- capital está parado de propósito.
INSERT INTO warehouse.stock (lot_id, quantity, zone)
SELECT
    l.id,
    x.resta,
    CASE
        WHEN p.is_vintage THEN 'bodega de guarda'
        WHEN p.family IN ('Vino tinto', 'Vino blanco', 'Cava') THEN 'bodega'
        WHEN p.family IN ('Queso', 'Ibérico') THEN 'refrigerado'
        ELSE 'seco'
    END
FROM warehouse.lots l
JOIN _resta x ON x.lot_id = l.id
JOIN assortment.products p ON p.id = l.product_id
ORDER BY l.id;

CREATE INDEX IF NOT EXISTS idx_lots_product ON warehouse.lots(product_id);
CREATE INDEX IF NOT EXISTS idx_lots_bb ON warehouse.lots(best_before);
CREATE INDEX IF NOT EXISTS idx_stock_lot ON warehouse.stock(lot_id);
CREATE INDEX IF NOT EXISTS idx_ol_order ON trade.order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_ol_lot ON trade.order_lines(lot_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON trade.orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON trade.orders(ordered_at);

ANALYZE assortment.products;
ANALYZE warehouse.lots;
ANALYZE warehouse.stock;
ANALYZE trade.customers;
ANALYZE trade.orders;
ANALYZE trade.order_lines;

COMMIT;
