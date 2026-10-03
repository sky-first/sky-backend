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
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Sintéticos e gerados por fórmula. Não vêm de nenhuma rede e não
-- descrevem nenhuma operação real — o que se demonstra é a pergunta.
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

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE kitchen.waste, service.order_items, service.orders,
         restaurant.staff_shifts, kitchen.products, restaurant.stores
    RESTART IDENTITY CASCADE;

-- 12 lojas em três formatos. As de carretera têm drive e vendem a
-- outras horas; as de centro comercial vivem da comida. O formato é a variável
-- que explica quase tudo o resto.
INSERT INTO restaurant.stores (name, city, format, seats, has_drive)
SELECT
    'Tienda ' || LPAD(g::TEXT, 2, '0'),
    (ARRAY['Madrid','Barcelona','Valencia','Sevilla','Zaragoza','Málaga',
           'Bilbao','Murcia','Valladolid','Badajoz','Alicante','Granada'])[g],
    (ARRAY['centro','carretera','centro comercial'])[1 + g % 3],
    (ARRAY[80, 120, 60])[1 + g % 3],
    ((1 + g % 3) = 2)
FROM generate_series(1, 12) g;

-- 40 artigos. O `hold_minutes` é a espinha dorsal da história da merma:
-- o que não se vende em dez minutos deita-se fora.
INSERT INTO kitchen.products (sku, name, family, unit_cost, menu_price, hold_minutes)
SELECT
    'ART-' || LPAD(g::TEXT, 3, '0'),
    -- Nomes de carta, e não `Patatas 27`.
    --
    -- O nome gerado (`familia || ' ' || g`) é a coisa mais visível num
    -- ecrã de demonstração a dizer «isto são dados de teste». O resto
    -- do conjunto está calibrado para ser crível; o nome do artigo
    -- desfazia-o de graça.
    --
    -- O índice: a família sai de `1 + g % 5`, portanto os oito artigos
    -- de cada família são os `g` com o mesmo resto. `1 + (g - 1) / 5`
    -- dá-lhes 1..8 dentro da família, para qualquer das cinco.
    -- Os dois subscritos: o Postgres não corta uma linha de um array
    -- 2-D com um índice só («cannot subscript type text»).
    fam.nomes[1 + g % 5][1 + (g - 1) / 5],
    fam.nome,
    custo.c,
    (custo.c * fam.mult)::NUMERIC(8,2),
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
        -- As bebidas têm a melhor margem e a pior merma (quase nenhuma);
        -- os hambúrgueres é ao contrário. É a tensão do negócio.
        (ARRAY[2.6, 2.8, 3.4, 5.2, 3.0])[1 + g % 5] AS mult,
        (ARRAY[10, 20, 7, 600, 240])[1 + g % 5] AS minutos
) fam
CROSS JOIN LATERAL (SELECT (0.60 + (g * 17) % 240 / 100.0)::NUMERIC(8,2) AS c) custo;

-- 90 dias de pedidos. 12 lojas × 5 faixas × 90 dias, com volume por faixa.
--
-- Quatro coisas plantadas de propósito:
--   • o jantar de sexta e sábado é o pico, e é onde o tempo de serviço
--     se degrada;
--   • as lojas de estrada vendem no drive e fora de horas;
--   • duas lojas (3 e 8) têm tempos de serviço muito piores que as
--     outras, à mesma hora e com o mesmo formato;
--   • o custo de pessoal por euro vendido dispara nas faixas vazias —
--     é lá que está o dinheiro, e não no pico.
INSERT INTO service.orders (store_id, placed_at, channel, day_part, service_sec, total)
SELECT
    s.id,
    momento.ts,
    canal.c,
    faixa.nome,
    GREATEST(60, tempo.seg)::INT,
    0
FROM restaurant.stores s
CROSS JOIN generate_series(0, 89) d
CROSS JOIN LATERAL (
    SELECT * FROM (VALUES
        ('desayuno', 8, 14),
        ('comida', 12, 46),
        ('tarde', 16, 16),
        ('cena', 20, 52),
        ('noche', 23, 10)
    ) AS f(nome, hora, pedidos)
) faixa
CROSS JOIN LATERAL generate_series(
    1,
    -- Sexta e sábado ao jantar: mais 60%.
    CASE
        WHEN faixa.nome = 'cena'
         AND EXTRACT(DOW FROM (CURRENT_DATE - d))::INT IN (5, 6)
        THEN (faixa.pedidos * 1.6)::INT
        ELSE faixa.pedidos
    END
) n
CROSS JOIN LATERAL (
    SELECT ((CURRENT_DATE - d)::TIMESTAMPTZ
            + (faixa.hora * INTERVAL '1 hour')
            + ((n * 7) % 60) * INTERVAL '1 minute') AS ts
) momento
CROSS JOIN LATERAL (
    SELECT CASE
        WHEN s.has_drive AND (n % 5) < 2 THEN 'drive'
        WHEN (n % 5) = 2 THEN 'quiosco'
        WHEN (n % 5) = 3 THEN 'entrega'
        ELSE 'mostrador'
    END AS c
) canal
CROSS JOIN LATERAL (
    SELECT
        -- Base 150s, mais a pressão do pico, mais o castigo das duas
        -- lojas lentas.
        -- Base 110s. Um balcão de restauração rápida serve em dois a
        -- três minutos; o patamar de serviço são os quatro.
        --
        -- A primeira versão arrancava nos 150 e somava 70 no pico, o que
        -- punha as lojas NORMAIS a falhar 75% dos pedidos à hora de
        -- almoço. Uma rede nesse estado não tem um problema de duas
        -- lojas — tem um problema de rede, e o ecrã deixa de apontar
        -- para onde interessa.
        110
        + CASE WHEN faixa.nome IN ('comida', 'cena') THEN 45 ELSE 0 END
        -- ⚠️ As duas lojas lentas só são lentas QUANDO ESTÃO CHEIAS.
        --
        -- A primeira versão somava o castigo sempre, e saíam 100% dos
        -- pedidos acima de quatro minutos — a toda a hora, incluindo às
        -- onze da noite com a casa vazia. Não é assim que uma loja
        -- falha: falha no pico, quando a cozinha não acompanha.
        --
        -- E um número absoluto («100%») é o que faz um director de
        -- operações fechar o ecrã: ninguém acredita numa loja que nunca
        -- serve ninguém em menos de quatro minutos.
        + CASE
            WHEN s.id IN (3, 8) AND faixa.nome IN ('comida', 'cena') THEN 45
            WHEN s.id IN (3, 8) THEN 15
            ELSE 0
          END
        + (ABS(hashint4(s.id * 1000 + d * 17 + n)) % 110)
        AS seg
) tempo;

-- As linhas de cada pedido: 1 a 3 artigos.
INSERT INTO service.order_items (order_id, product_id, quantity, unit_price)
SELECT
    o.id,
    p.id,
    -- ⚠️ O canal tem de mexer no cesto, senão o ticket é igual nos
    -- quatro.
    --
    -- Com a quantidade a depender só do artigo, os quatro canais davam
    -- 36,35 / 36,38 / 36,41 / 36,49 € de ticket médio — e a resposta à
    -- pergunta «que canal traz o ticket?» apresentava onze cêntimos
    -- como se fossem um achado. Quem olha vê quatro números iguais e
    -- uma conclusão vazia, que é pior do que não ter a pergunta.
    --
    -- A diferença é a do negócio real: a entrega é um pedido de casa,
    -- com várias pessoas; o drive é quase sempre de um.
    CASE o.channel
        WHEN 'entrega' THEN 2 + ABS(hashint4(o.id * 31 + p.id)) % 3
        WHEN 'drive'   THEN 1 + ABS(hashint4(o.id * 31 + p.id)) % 2
        ELSE                1 + ABS(hashint4(o.id * 31 + p.id)) % 3
    END,
    p.menu_price
FROM service.orders o
CROSS JOIN LATERAL (
    SELECT id, menu_price FROM kitchen.products
    WHERE id IN (
        1 + ABS(hashint4(o.id * 7)) % 40,
        1 + ABS(hashint4(o.id * 23)) % 40,
        1 + ABS(hashint4(o.id * 53)) % 40
    )
) p;

-- O total do pedido sai das linhas, para os dois nunca discordarem.
UPDATE service.orders o
SET total = x.soma
FROM (
    SELECT order_id, ROUND(SUM(quantity * unit_price), 2) AS soma
    FROM service.order_items GROUP BY order_id
) x
WHERE x.order_id = o.id;

-- A escala. O custo por hora sobe à noite e ao fim de semana.
--
-- O ponto da história: nas faixas vazias o pessoal é quase o mesmo e as
-- vendas não são — e é aí que o custo por euro vendido explode.
INSERT INTO restaurant.staff_shifts (store_id, worked_on, day_part, headcount, hours, cost_per_hour)
SELECT
    s.id,
    (CURRENT_DATE - d)::DATE,
    faixa.nome,
    faixa.pessoas,
    (faixa.pessoas * 4)::NUMERIC(6,2),
    (CASE WHEN faixa.nome = 'noche' THEN 11.40 ELSE 9.20 END)::NUMERIC(6,2)
FROM restaurant.stores s
CROSS JOIN generate_series(0, 89) d
CROSS JOIN LATERAL (
    SELECT * FROM (VALUES
        ('desayuno', 3),
        ('comida', 7),
        ('tarde', 4),
        ('cena', 8),
        ('noche', 3)
    ) AS f(nome, pessoas)
) faixa;

-- A merma. Concentra-se no que tem validade curta, e nas faixas a
-- seguir ao pico — preparou-se para a onda que não veio.
INSERT INTO kitchen.waste (store_id, product_id, wasted_on, day_part, units, reason)
SELECT
    s.id,
    p.id,
    (CURRENT_DATE - d)::DATE,
    faixa.nome,
    1 + ABS(hashint4(s.id * 100 + p.id + d)) % 7,
    CASE
        WHEN p.hold_minutes <= 10 THEN 'caducidad'
        WHEN faixa.nome IN ('tarde', 'noche') THEN 'preparado de más'
        ELSE 'error de pedido'
    END
FROM restaurant.stores s
CROSS JOIN generate_series(0, 89) d
CROSS JOIN LATERAL (
    SELECT * FROM (VALUES ('tarde'), ('noche'), ('comida')) AS f(nome)
) faixa
JOIN kitchen.products p
  ON p.id = 1 + ABS(hashint4(s.id * 13 + d * 7 + length(faixa.nome))) % 40
-- Só os artigos de validade curta geram merma a sério.
WHERE p.hold_minutes <= 20;

CREATE INDEX IF NOT EXISTS idx_orders_store ON service.orders(store_id);
CREATE INDEX IF NOT EXISTS idx_orders_placed ON service.orders(placed_at);
CREATE INDEX IF NOT EXISTS idx_items_order ON service.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON service.order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_waste_store ON kitchen.waste(store_id);
CREATE INDEX IF NOT EXISTS idx_shifts_store ON restaurant.staff_shifts(store_id);

COMMIT;
