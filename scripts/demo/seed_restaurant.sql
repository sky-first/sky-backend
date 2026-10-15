-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Restauração / Operação de lojas
-- ─────────────────────────────────────────────────────────────────
-- Numa rede de restauração toda a gente sabe quanto se vendeu ontem. O
-- que ninguém sabe dizer de cabeça é o que decide a margem:
--
--   • quanto do produto preparado acaba no lixo, e em que turno;
--   • quanto custa a hora de pessoal por cada euro vendido, hora a hora;
--   • quanto tempo demora um pedido, e a que horas é que isso piora.
--
-- Nenhuma destas se responde num sistema só. As vendas estão na caixa,
-- as horas estão na escala, a merma está numa folha do turno, e o
-- tempo de serviço está no ecrã da cozinha. Cada um sabe uma parte.
--
--   restaurant.stores        — as lojas, com o seu formato
--   restaurant.staff_shifts  — quem esteve, quantas horas, a que custo
--   service.orders           — cada pedido: canal, hora, tempo, total
--   service.order_items      — o que foi vendido, e por quanto
--   kitchen.products         — custo e preço de cada artigo
--   kitchen.waste            — o que se preparou e não se vendeu
--
-- ── Porque é que isto foi reescrito (15/10/2026) ─────────────────
--
-- As doze lojas tinham exactamente os mesmos pedidos por dia — a «loja
-- com mais pedidos no último mês» ganhava por desempate — e os cinco
-- pratos mais vendidos da semana ficavam todos à volta das 850 unidades
-- com 17 de diferença. Os artigos saíam ao calhas, todos com a mesma
-- probabilidade, e uma água custava mais do que um hambúrguer.
--
-- Agora cada loja tem o seu tamanho (Madrid não vende o que vende
-- Badajoz), o formato decide as horas (o centro comercial vive do
-- almoço e da tarde; a de estrada vende de noite e no drive), o fim de
-- semana enche, e o cesto monta-se como se monta ao balcão: um prato,
-- quase sempre batatas e bebida, às vezes sobremesa — com os artigos de
-- sempre a vender muito mais do que os da novidade.
--
-- O que a demonstração conta continua igual: as lojas 3 e 8 são lentas
-- na hora de ponta, o pessoal pesa mais nas faixas vazias, a merma
-- separa-se em caducidade e excesso, o mostrador traz o importe e a
-- entrega traz o ticket.
--
-- ── Aleatório, mas sempre o mesmo ────────────────────────────────
--
-- `pg_temp.u(...)` é um hash dos argumentos: a mesma chave dá sempre o
-- mesmo número, em qualquer carga. As funções vivem em `pg_temp` e
-- morrem com a sessão. As datas contam a partir de hoje, e nada fica
-- no futuro: os pedidos de hoje só até à hora do carregamento.
--
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Sintéticos. Não vêm de nenhuma rede e não descrevem nenhuma operação
-- real — o que se demonstra é a pergunta.
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS restaurant;
CREATE SCHEMA IF NOT EXISTS service;
CREATE SCHEMA IF NOT EXISTS kitchen;

CREATE TABLE IF NOT EXISTS restaurant.stores (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT NOT NULL,
    format      TEXT NOT NULL,          -- centro | carretera | centro comercial
    seats       INT NOT NULL,
    has_drive   BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS restaurant.staff_shifts (
    id            SERIAL PRIMARY KEY,
    store_id      INT NOT NULL REFERENCES restaurant.stores(id),
    worked_on     DATE NOT NULL,
    day_part      TEXT NOT NULL,        -- desayuno | comida | tarde | cena | noche
    headcount     INT NOT NULL,
    hours         NUMERIC(6,2) NOT NULL,
    cost_per_hour NUMERIC(6,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS kitchen.products (
    id         SERIAL PRIMARY KEY,
    sku        TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    family     TEXT NOT NULL,
    unit_cost  NUMERIC(8,2) NOT NULL,
    menu_price NUMERIC(8,2) NOT NULL,
    -- Minutos de validade depois de preparado. É isto que separa um
    -- hambúrguer de uma bebida: um morre em dez minutos, a outra não.
    hold_minutes INT NOT NULL
);

CREATE TABLE IF NOT EXISTS service.orders (
    id            SERIAL PRIMARY KEY,
    store_id      INT NOT NULL REFERENCES restaurant.stores(id),
    placed_at     TIMESTAMPTZ NOT NULL,
    channel       TEXT NOT NULL,        -- mostrador | quiosco | drive | entrega
    day_part      TEXT NOT NULL,
    service_sec   INT NOT NULL,         -- do pedido à entrega
    total         NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS service.order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL REFERENCES service.orders(id),
    product_id INT NOT NULL REFERENCES kitchen.products(id),
    quantity   INT NOT NULL,
    unit_price NUMERIC(8,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS kitchen.waste (
    id         SERIAL PRIMARY KEY,
    store_id   INT NOT NULL REFERENCES restaurant.stores(id),
    product_id INT NOT NULL REFERENCES kitchen.products(id),
    wasted_on  DATE NOT NULL,
    day_part   TEXT NOT NULL,
    units      INT NOT NULL,
    reason     TEXT NOT NULL           -- caducidad | preparado de más | error de pedido
);

-- ── o gerador ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION pg_temp.u(VARIADIC k INT[]) RETURNS FLOAT8
LANGUAGE sql IMMUTABLE AS $$
    SELECT (hashtext('restauracion:' || array_to_string(k, ':')) & 2147483647)::FLOAT8
           / 2147483648.0
$$;

CREATE OR REPLACE FUNCTION pg_temp.z(VARIADIC k INT[]) RETURNS FLOAT8
LANGUAGE sql IMMUTABLE AS $$
    SELECT sqrt(-2 * ln(GREATEST(pg_temp.u(VARIADIC k || 1), 1e-9)))
           * cos(2 * pi() * pg_temp.u(VARIADIC k || 2))
$$;

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE kitchen.waste, service.order_items, service.orders,
         restaurant.staff_shifts, kitchen.products, restaurant.stores
    RESTART IDENTITY CASCADE;

-- 12 lojas em três formatos. As de carretera têm drive e vendem a
-- outras horas; as de centro comercial vivem da comida. O formato é a
-- variável que explica quase tudo o resto — e o tamanho da cidade
-- explica o volume.
INSERT INTO restaurant.stores (name, city, format, seats, has_drive)
SELECT
    'Tienda ' || LPAD(g::TEXT, 2, '0'),
    (ARRAY['Madrid','Barcelona','Valencia','Sevilla','Zaragoza','Málaga',
           'Bilbao','Murcia','Valladolid','Badajoz','Alicante','Granada'])[g],
    (ARRAY['centro','carretera','centro comercial'])[1 + g % 3],
    (ARRAY[80, 120, 60])[1 + g % 3],
    ((1 + g % 3) = 2)
FROM generate_series(1, 12) g;

CREATE TEMP TABLE _s ON COMMIT DROP AS
SELECT
    s.id,
    s.format,
    s.has_drive,
    -- Volume relativo da loja: a cidade e um pouco de sorte de localização.
    (ARRAY[1.45, 1.35, 1.10, 1.05, 0.90, 1.00, 0.95, 0.85, 0.80, 0.70, 0.90, 0.75])[s.id]
        * (0.94 + 0.12 * pg_temp.u(s.id, 1)) AS tam,
    -- Merma relativa: a 8 (lenta) e a 11 preparam de mais.
    CASE s.id WHEN 8 THEN 1.5 WHEN 11 THEN 1.4
              ELSE 0.80 + 0.35 * pg_temp.u(s.id, 2) END AS merma,
    -- Custo da hora: as cidades grandes pagam mais.
    CASE WHEN s.city IN ('Madrid', 'Barcelona', 'Bilbao') THEN 1.08
         WHEN s.city IN ('Badajoz', 'Murcia', 'Granada') THEN 0.95
         ELSE 1.0 END AS custo_cidade
FROM restaurant.stores s;

-- 40 artigos. O `hold_minutes` é a espinha dorsal da história da merma:
-- o que não se vende em dez minutos deita-se fora.
--
-- Os nomes, as famílias e os SKU são os de sempre (a família sai de
-- `1 + g % 5`, o artigo de `1 + (g - 1) / 5`). O custo passa a ser o do
-- artigo — uma água custa vinte cêntimos e um menu premium dois euros e
-- meio — e a margem varia dentro da família, em vez de ser a mesma
-- fracção para os oito.
INSERT INTO kitchen.products (sku, name, family, unit_cost, menu_price, hold_minutes)
SELECT
    'ART-' || LPAD(g::TEXT, 3, '0'),
    fam.nomes[1 + g % 5][1 + (g - 1) / 5],
    fam.nome,
    fam.custos[1 + g % 5][1 + (g - 1) / 5]::NUMERIC(8,2),
    ROUND((fam.custos[1 + g % 5][1 + (g - 1) / 5] * fam.mult
           * (0.92 + 0.16 * pg_temp.u(g, 3)))::NUMERIC, 1) - 0.01,
    fam.minutos
FROM generate_series(1, 40) g
CROSS JOIN LATERAL (
    SELECT
        (ARRAY['Hamburguesas','Pollo','Patatas','Bebidas','Postres'])[1 + g % 5] AS nome,
        (ARRAY[
            ARRAY['Clásica','Doble','Con queso','Picante','De pollo crujiente',
                  'Vegetal','Barbacoa','Premium'],
            ARRAY['Alitas 6','Alitas 12','Tiras de pollo','Nuggets 6','Nuggets 12',
                  'Wrap de pollo','Ensalada de pollo','Pollo asado'],
            ARRAY['Patatas pequeñas','Patatas medianas','Patatas grandes',
                  'Patatas deluxe','Gajos','Patatas con queso','Patatas con bacon',
                  'Aros de cebolla'],
            ARRAY['Refresco pequeño','Refresco mediano','Refresco grande','Agua',
                  'Zumo de naranja','Café','Batido','Té helado'],
            ARRAY['Cono de helado','Sundae de chocolate','Sundae de fresa',
                  'Tarta de manzana','Brownie','Donut','Natillas','Yogur con fruta']
        ]) AS nomes,
        (ARRAY[
            ARRAY[1.10, 1.85, 1.30, 1.35, 1.40, 1.50, 1.55, 2.40],
            ARRAY[1.30, 2.40, 1.50, 0.90, 1.70, 1.20, 1.60, 2.80],
            ARRAY[0.25, 0.35, 0.45, 0.55, 0.50, 0.70, 0.80, 0.60],
            ARRAY[0.18, 0.24, 0.30, 0.20, 0.55, 0.22, 0.70, 0.25],
            ARRAY[0.25, 0.55, 0.55, 0.45, 0.60, 0.35, 0.40, 0.50]
        ]) AS custos,
        -- As bebidas têm a melhor margem e a pior merma (quase nenhuma);
        -- os hambúrgueres é ao contrário. É a tensão do negócio.
        (ARRAY[2.6, 2.8, 3.4, 5.2, 3.0])[1 + g % 5] AS mult,
        (ARRAY[10, 20, 7, 600, 240])[1 + g % 5] AS minutos
) fam;

-- O peso de cada artigo nas vendas, dentro da família. Ao pequeno-almoço
-- vende-se café, sumo e donut; no resto do dia, os clássicos.
CREATE TEMP TABLE _cump ON COMMIT DROP AS
WITH w AS (
    SELECT p.id, p.family, cedo.c AS desayuno,
           (CASE p.family
               WHEN 'Hamburguesas' THEN (ARRAY[1.60, 1.10, 1.40, 0.60, 0.90, 0.35, 0.70, 0.45])
               WHEN 'Pollo'        THEN (ARRAY[0.80, 0.60, 1.00, 1.30, 0.70, 0.60, 0.35, 0.30])
               WHEN 'Patatas'      THEN (ARRAY[0.70, 2.00, 1.10, 0.50, 0.60, 0.45, 0.35, 0.40])
               WHEN 'Bebidas'      THEN CASE WHEN cedo.c
                                             THEN (ARRAY[0.30, 0.40, 0.20, 0.60, 1.60, 3.00, 0.30, 0.20])
                                             ELSE (ARRAY[0.80, 1.80, 1.00, 0.70, 0.35, 0.60, 0.45, 0.40]) END
               ELSE                     CASE WHEN cedo.c
                                             THEN (ARRAY[0.10, 0.10, 0.10, 0.50, 0.40, 2.20, 0.30, 1.20])
                                             ELSE (ARRAY[1.20, 0.70, 0.45, 0.50, 0.40, 0.80, 0.25, 0.30]) END
            END)[1 + (p.id - 1) / 5] AS w
    FROM kitchen.products p
    CROSS JOIN (VALUES (TRUE), (FALSE)) AS cedo(c)
)
SELECT id, family, desayuno, w,
       COALESCE(SUM(w) OVER (PARTITION BY family, desayuno ORDER BY id
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
           / SUM(w) OVER (PARTITION BY family, desayuno) AS lo,
       SUM(w) OVER (PARTITION BY family, desayuno ORDER BY id)
           / SUM(w) OVER (PARTITION BY family, desayuno) AS hi
FROM w;

-- ── Os pedidos ───────────────────────────────────────────────────
--
-- 90 dias (hoje incluído) × 12 lojas × 5 faixas. Quantos pedidos em cada
-- uma: o formato decide a forma do dia, o tamanho da loja decide o
-- volume, o fim de semana enche (o jantar de sexta e sábado é o pico, e
-- é onde o tempo de serviço se degrada), Agosto puxa pelas de estrada,
-- e cada dia tem o seu acaso.
--
-- Quatro coisas plantadas de propósito:
--   • o jantar de sexta e sábado é o pico;
--   • as lojas de estrada vendem no drive e fora de horas;
--   • duas lojas (3 e 8) têm tempos de serviço muito piores que as
--     outras, à mesma hora e com o mesmo formato;
--   • o custo de pessoal por euro vendido dispara nas faixas vazias —
--     é lá que está o dinheiro, e não no pico.
CREATE TEMP TABLE _fx ON COMMIT DROP AS
SELECT
    s.id AS store_id,
    d.d,
    f.nome,
    f.hora,
    f.minutos,
    GREATEST(1, ROUND(
        CASE s.format
            WHEN 'centro'    THEN f.centro
            WHEN 'carretera' THEN f.estrada
            ELSE f.cc
        END
        * s.tam
        * (ARRAY[1.10, 0.82, 0.86, 0.92, 0.98, 1.15, 1.30])
            [1 + EXTRACT(DOW FROM CURRENT_DATE - d.d)::INT]
        * CASE WHEN f.nome = 'cena'
                AND EXTRACT(DOW FROM CURRENT_DATE - d.d)::INT IN (5, 6) THEN 1.25 ELSE 1 END
        * CASE WHEN s.format = 'carretera'
                AND EXTRACT(MONTH FROM CURRENT_DATE - d.d)::INT IN (7, 8) THEN 1.15 ELSE 1 END
        * exp(0.08 * pg_temp.z(s.id, d.d, f.ordem, 10))
    ))::INT AS pedidos
FROM _s s
CROSS JOIN generate_series(0, 89) AS d(d)
CROSS JOIN (VALUES
    -- faixa, ordem, hora de início, duração (min), pedidos/dia por formato
    ('desayuno', 1,  7, 240, 22, 20,  6),
    ('comida',   2, 12, 240, 50, 40, 58),
    ('tarde',    3, 16, 240, 18, 16, 28),
    ('cena',     4, 20, 180, 44, 42, 46),
    ('noche',    5, 23, 120, 12, 20,  3)
) AS f(nome, ordem, hora, minutos, centro, estrada, cc);

CREATE TEMP TABLE _ped ON COMMIT DROP AS
SELECT
    fx.store_id,
    fx.d,
    fx.nome AS day_part,
    n.n,
    ((CURRENT_DATE - fx.d)::TIMESTAMP
        + fx.hora * INTERVAL '1 hour'
        + (pg_temp.u(fx.store_id, fx.d, n.n, length(fx.nome), 11) * fx.minutos)::INT
          * INTERVAL '1 minute') AS placed_at,
    pg_temp.u(fx.store_id, fx.d, n.n, length(fx.nome), 12) AS uc
FROM _fx fx
CROSS JOIN LATERAL generate_series(1, fx.pedidos) AS n(n);

INSERT INTO service.orders (store_id, placed_at, channel, day_part, service_sec, total)
SELECT
    p.store_id,
    p.placed_at,
    canal.c,
    p.day_part,
    GREATEST(60, (
        -- Base 110 s. Um balcão de restauração rápida serve em dois a
        -- três minutos; o patamar de serviço são os quatro.
        110
        + CASE WHEN p.day_part IN ('comida', 'cena') THEN 45 ELSE 0 END
        -- ⚠️ As duas lojas lentas só são lentas QUANDO ESTÃO CHEIAS.
        -- Uma loja não falha a toda a hora: falha no pico, quando a
        -- cozinha não acompanha.
        + CASE
            WHEN p.store_id IN (3, 8) AND p.day_part IN ('comida', 'cena') THEN 45
            WHEN p.store_id IN (3, 8) THEN 15
            ELSE 0
          END
        + CASE canal.c WHEN 'entrega' THEN 15 WHEN 'drive' THEN 8
                       WHEN 'quiosco' THEN -6 ELSE 0 END
        + CASE WHEN p.day_part = 'cena'
                AND EXTRACT(DOW FROM p.placed_at)::INT IN (5, 6) THEN 8 ELSE 0 END
        + pg_temp.u(p.store_id, p.d, p.n, length(p.day_part), 13) * 110
    ))::INT,
    0
FROM _ped p
JOIN _s s ON s.id = p.store_id
CROSS JOIN LATERAL (
    SELECT CASE
        -- A de estrada vive do drive; o centro comercial do quiosco; a
        -- entrega pesa mais ao jantar.
        WHEN s.has_drive THEN
            CASE WHEN p.uc < 0.42 THEN 'drive' WHEN p.uc < 0.75 THEN 'mostrador'
                 WHEN p.uc < 0.90 THEN 'quiosco' ELSE 'entrega' END
        WHEN s.format = 'centro' THEN
            CASE WHEN p.uc < CASE WHEN p.day_part = 'cena' THEN 0.32 ELSE 0.20 END THEN 'entrega'
                 WHEN p.uc < 0.47 THEN 'quiosco' ELSE 'mostrador' END
        ELSE
            CASE WHEN p.uc < 0.12 THEN 'entrega' WHEN p.uc < 0.50 THEN 'quiosco'
                 ELSE 'mostrador' END
    END AS c
) canal
WHERE p.placed_at <= now()
ORDER BY p.placed_at, p.store_id;

-- ── O cesto ──────────────────────────────────────────────────────
--
-- Monta-se como ao balcão: um prato (hambúrguer ou frango), quase sempre
-- batatas e bebida, às vezes sobremesa; a entrega leva um segundo prato
-- porque é para a casa toda. Ao pequeno-almoço o prato é raro e a bebida
-- é café ou sumo. Dentro de cada família, os artigos de sempre vendem
-- muito mais do que os da novidade.
--
-- ⚠️ O canal mexe no cesto e na quantidade, senão o ticket é igual nos
-- quatro: a entrega é um pedido de casa, com várias pessoas; o drive é
-- quase sempre de um.
INSERT INTO service.order_items (order_id, product_id, quantity, unit_price)
SELECT x.order_id, x.product_id, x.qty, p.menu_price
FROM (
    SELECT DISTINCT ON (o.id, cp.id)
        o.id AS order_id,
        cp.id AS product_id,
        CASE o.channel
            WHEN 'entrega' THEN 1 + (pg_temp.u(o.id, slot.k, 22) * 3.2)::INT
            WHEN 'drive'   THEN 1 + (pg_temp.u(o.id, slot.k, 22) < 0.15)::INT
            ELSE                1 + (pg_temp.u(o.id, slot.k, 22) < 0.25)::INT
        END AS qty
    FROM service.orders o
    CROSS JOIN LATERAL (VALUES
        -- slot, família, probabilidade (dia / pequeno-almoço)
        (1, CASE WHEN pg_temp.u(o.id, 1, 20) < 0.58 THEN 'Hamburguesas' ELSE 'Pollo' END, 0.92, 0.30),
        (2, 'Patatas', 0.72, 0.10),
        (3, 'Bebidas', 0.85, 0.97),
        (4, 'Postres', CASE WHEN o.day_part = 'tarde' THEN 0.45 ELSE 0.20 END, 0.50),
        (5, CASE WHEN pg_temp.u(o.id, 5, 20) < 0.5 THEN 'Hamburguesas' ELSE 'Pollo' END,
            CASE WHEN o.channel = 'entrega' THEN 0.60 ELSE 0.04 END, 0.0)
    ) AS slot(k, familia, p_dia, p_cedo)
    JOIN _cump cp
      ON cp.family = slot.familia
     AND cp.desayuno = (o.day_part = 'desayuno')
     AND pg_temp.u(o.id, slot.k, 21) >= cp.lo
     AND pg_temp.u(o.id, slot.k, 21) <  cp.hi
    WHERE pg_temp.u(o.id, slot.k, 23) <
          CASE WHEN o.day_part = 'desayuno' THEN slot.p_cedo ELSE slot.p_dia END
       -- Nenhum pedido sai vazio: a bebida entra sempre que não houver
       -- prato nem batatas.
       OR (slot.k = 3
           AND pg_temp.u(o.id, 1, 23) >= CASE WHEN o.day_part = 'desayuno' THEN 0.30 ELSE 0.92 END
           AND pg_temp.u(o.id, 2, 23) >= CASE WHEN o.day_part = 'desayuno' THEN 0.10 ELSE 0.72 END)
    ORDER BY o.id, cp.id, slot.k
) x
JOIN kitchen.products p ON p.id = x.product_id
ORDER BY x.order_id, x.product_id;

-- O total do pedido sai das linhas, para os dois nunca discordarem.
UPDATE service.orders o
SET total = x.soma
FROM (
    SELECT order_id, ROUND(SUM(quantity * unit_price), 2) AS soma
    FROM service.order_items GROUP BY order_id
) x
WHERE x.order_id = o.id;

-- ── A escala ─────────────────────────────────────────────────────
--
-- O ponto da história: nas faixas vazias o pessoal é quase o mesmo e as
-- vendas não são — e é aí que o custo por euro vendido explode. A
-- equipa cresce com a loja, mas menos do que as vendas (há um mínimo
-- para abrir a porta). O custo por hora sobe à noite e ao fim de
-- semana, e nas cidades grandes.
--
-- Duas lojas têm gente a mais nas horas mortas, comparadas com as do
-- mesmo formato: a 10 (estrada) à tarde e à noite, a 5 (centro
-- comercial) ao pequeno-almoço e à tarde. É o que o agente "Horas de
-- personal por tienda" procura.
INSERT INTO restaurant.staff_shifts (store_id, worked_on, day_part, headcount, hours, cost_per_hour)
SELECT
    s.id,
    (CURRENT_DATE - d.d)::DATE,
    f.nome,
    eq.n,
    ROUND((eq.n * (3.6 + 0.8 * pg_temp.u(s.id, d.d, f.ordem, 30)))::NUMERIC, 2),
    ROUND(((CASE
                WHEN f.nome = 'noche' THEN 11.40
                WHEN EXTRACT(DOW FROM CURRENT_DATE - d.d)::INT IN (0, 6) THEN 10.10
                ELSE 9.20
            END) * s.custo_cidade)::NUMERIC, 2)
FROM _s s
CROSS JOIN generate_series(0, 89) AS d(d)
CROSS JOIN (VALUES
    ('desayuno', 1,  7, 3, 3, 2),
    ('comida',   2, 12, 7, 6, 8),
    ('tarde',    3, 16, 4, 4, 5),
    ('cena',     4, 20, 8, 8, 8),
    ('noche',    5, 23, 3, 4, 1)
) AS f(nome, ordem, hora, centro, estrada, cc)
CROSS JOIN LATERAL (
    SELECT GREATEST(1, ROUND(
               CASE s.format WHEN 'centro' THEN f.centro
                             WHEN 'carretera' THEN f.estrada ELSE f.cc END
               * (0.60 + 0.40 * s.tam)
               + CASE WHEN f.nome = 'cena'
                       AND EXTRACT(DOW FROM CURRENT_DATE - d.d)::INT IN (5, 6) THEN 1 ELSE 0 END
               + CASE WHEN s.id = 10 AND f.nome IN ('tarde', 'noche') THEN 1.5
                      WHEN s.id = 5  AND f.nome IN ('desayuno', 'tarde') THEN 2 ELSE 0 END
               + (pg_temp.u(s.id, d.d, f.ordem, 31) - 0.5)
           ))::INT AS n
) eq
-- Hoje, só as faixas que já começaram.
WHERE (CURRENT_DATE - d.d) + f.hora * INTERVAL '1 hour' <= now();

-- ── A merma ──────────────────────────────────────────────────────
--
-- Concentra-se no que tem validade curta, e nas faixas a seguir ao pico
-- — preparou-se para a onda que não veio. Cada loja tem o seu hábito:
-- a 8 e a 11 tiram do lixo bem mais do que as outras. Vai até ontem: a
-- folha de merma fecha-se no fim do dia.
INSERT INTO kitchen.waste (store_id, product_id, wasted_on, day_part, units, reason)
SELECT
    s.id,
    p.id,
    (CURRENT_DATE - d.d)::DATE,
    f.nome,
    GREATEST(1, ROUND(1 + power(pg_temp.u(s.id, d.d, f.ordem, k.k, 40), 1.3)
                          * 7 * s.merma * (0.6 + 0.4 * s.tam)))::INT,
    CASE
        WHEN pg_temp.u(s.id, d.d, f.ordem, k.k, 41) < 0.10 THEN 'error de pedido'
        WHEN p.hold_minutes <= 10 AND f.nome IN ('comida', 'cena') THEN 'caducidad'
        WHEN p.hold_minutes <= 10 AND pg_temp.u(s.id, d.d, f.ordem, k.k, 42) < 0.55 THEN 'caducidad'
        ELSE 'preparado de más'
    END
FROM _s s
CROSS JOIN generate_series(1, 90) AS d(d)
CROSS JOIN (VALUES ('comida', 2), ('tarde', 3), ('cena', 4), ('noche', 5)) AS f(nome, ordem)
CROSS JOIN generate_series(1, 3) AS k(k)
JOIN kitchen.products p
  ON p.id = 1 + (pg_temp.u(s.id, d.d, f.ordem, k.k, 43) * 40)::INT % 40
WHERE
    -- Só os artigos de validade curta geram merma a sério; as bebidas e
    -- as sobremesas quase nunca.
    pg_temp.u(s.id, d.d, f.ordem, k.k, 44) <
        CASE WHEN p.hold_minutes <= 20 THEN 0.85 ELSE 0.04 END
    -- A noite do centro comercial quase não existe.
    AND NOT (s.format = 'centro comercial' AND f.nome = 'noche'
             AND pg_temp.u(s.id, d.d, k.k, 45) < 0.8);

CREATE INDEX IF NOT EXISTS idx_orders_store ON service.orders(store_id);
CREATE INDEX IF NOT EXISTS idx_orders_placed ON service.orders(placed_at);
CREATE INDEX IF NOT EXISTS idx_items_order ON service.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON service.order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_waste_store ON kitchen.waste(store_id);
CREATE INDEX IF NOT EXISTS idx_shifts_store ON restaurant.staff_shifts(store_id);

ANALYZE restaurant.stores;
ANALYZE restaurant.staff_shifts;
ANALYZE service.orders;
ANALYZE service.order_items;
ANALYZE kitchen.products;
ANALYZE kitchen.waste;

COMMIT;
