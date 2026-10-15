-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Logística e Transportes
-- ─────────────────────────────────────────────────────────────────
-- Numa transportadora toda a gente sabe quantos camiões tem e quanto
-- faturou. O que ninguém sabe dizer de cabeça é o que decide o ano:
--
--   • que viaturas custam mais por quilómetro do que rendem;
--   • quantos quilómetros se andam vazios, e em que troços;
--   • que rotas chegam tarde, e a que clientes é que isso dói.
--
-- Nenhuma destas perguntas se responde num sistema só. O gasóleo está
-- no cartão de combustível, as horas estão no tacógrafo, o preço está
-- na nota de porte, e a hora de chegada está no telemóvel do motorista.
-- Cada um sabe uma parte. A conta é a junção — e é a junção que ninguém
-- faz todas as semanas.
--
--   fleet.vehicles           — a viatura, e o que custa tê-la parada
--   fleet.drivers            — quem conduz, e a que custo/hora
--   fleet.maintenance_jobs   — oficina: preventiva, pneus e avaria
--   ops.routes               — origem, destino, distância, portagens
--   ops.trips                — cada viagem: km, gasóleo, horas, chegada
--   freight.clients          — quem paga o porte, e com que tolerância
--   freight.shipments        — a carga que seguiu, quando, e por quanto
--
-- ── Porque é que isto foi reescrito (15/10/2026) ─────────────────
--
-- A bateria de perguntas de 14/10 em produção:
--
--   • «¿Cuántos viajes hizo cada vehículo el último mes?» → os 18
--     com exactamente 15. Cada viatura tinha 280 viagens espaçadas de
--     dois em dois dias, por construção;
--   • «envíos tarde el último mes» 160, «envíos por cliente el último
--     mes» a somar ~20, e «el cliente con más envíos este año» com 365.
--     O porte não tinha data nenhuma — a data vivia na viagem, noutro
--     esquema — e o motor inventou o filtro.
--
-- Agora as viaturas trabalham como viaturas: cada uma tem a sua taxa
-- de ocupação, folga ao domingo, trabalha menos em Agosto, não sai
-- enquanto está na oficina, e as ligeiras fazem dois serviços curtos
-- por dia. O porte leva a sua data de expedição, a hora prometida e a
-- hora de entrega, e por isso "tarde", "último mês" e "por cliente"
-- contam as mesmas linhas.
--
-- ── Aleatório, mas sempre o mesmo ────────────────────────────────
--
-- `pg_temp.u(...)` é um hash dos argumentos: a mesma chave dá sempre o
-- mesmo número. Nada de random(), que depende da ordem de execução. As
-- funções vivem em `pg_temp` e morrem com a sessão.
--
-- As viagens vão até ONTEM: só entra o que já chegou, para não haver
-- portes "entregues" no futuro. O Job recarrega todos os dias.
--
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Os dados são sintéticos. Não vêm de nenhum cliente e não descrevem
-- nenhuma operação real — o que se demonstra é a pergunta, não a empresa.
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS fleet;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS freight;

CREATE TABLE IF NOT EXISTS fleet.vehicles (
    id            SERIAL PRIMARY KEY,
    plate         TEXT NOT NULL UNIQUE,
    model         TEXT NOT NULL,
    class         TEXT NOT NULL,          -- ligeiro | semi-reboque | frigorífico
    acquired_on   DATE NOT NULL,
    capacity_kg   INT NOT NULL,
    -- Custo fixo mensal: leasing, seguro, imposto. Não depende de andar,
    -- e é o que transforma uma viatura parada em prejuízo.
    fixed_cost_month NUMERIC(8,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS fleet.drivers (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    licence       TEXT NOT NULL,
    hired_on      DATE NOT NULL,
    cost_per_hour NUMERIC(6,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS fleet.maintenance_jobs (
    id            SERIAL PRIMARY KEY,
    vehicle_id    INT NOT NULL REFERENCES fleet.vehicles(id),
    done_on       DATE NOT NULL,
    kind          TEXT NOT NULL,          -- preventiva | avaria | pneus
    cost          NUMERIC(10,2) NOT NULL,
    days_off_road INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops.routes (
    id               SERIAL PRIMARY KEY,
    origin           TEXT NOT NULL,
    destination      TEXT NOT NULL,
    distance_km      INT NOT NULL,
    standard_minutes INT NOT NULL,
    toll_cost        NUMERIC(8,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.trips (
    id              SERIAL PRIMARY KEY,
    vehicle_id      INT NOT NULL REFERENCES fleet.vehicles(id),
    driver_id       INT NOT NULL REFERENCES fleet.drivers(id),
    route_id        INT NOT NULL REFERENCES ops.routes(id),
    departed_at     TIMESTAMPTZ NOT NULL,
    planned_arrival TIMESTAMPTZ NOT NULL,
    arrived_at      TIMESTAMPTZ NOT NULL,
    km_run          INT NOT NULL,
    fuel_litres     NUMERIC(8,2) NOT NULL,
    driver_hours    NUMERIC(6,2) NOT NULL,
    status          TEXT NOT NULL         -- completed | cancelled
);

CREATE TABLE IF NOT EXISTS freight.clients (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    sector      TEXT NOT NULL,
    -- Minutos de tolerância contratados antes de a chegada contar como
    -- atraso. Varia por cliente, e é por isso que "chegou tarde" não é
    -- a mesma coisa para todos.
    sla_minutes INT NOT NULL
);

CREATE TABLE IF NOT EXISTS freight.shipments (
    id        SERIAL PRIMARY KEY,
    trip_id   INT NOT NULL REFERENCES ops.trips(id),
    client_id INT NOT NULL REFERENCES freight.clients(id),
    weight_kg INT NOT NULL,
    pallets   INT NOT NULL,
    revenue   NUMERIC(10,2) NOT NULL,
    incident  TEXT                        -- NULL = sem incidente
);

-- ── Colunas acrescentadas a 15/10/2026 ───────────────────────────
--
-- A nota de porte tem data. Sem ela, "quantos portes no último mês" e
-- "quantos chegaram tarde" só se respondiam juntando com `ops.trips`,
-- noutra ligação — e a resposta da bateria foi inventada. São cópias
-- da viagem: `shipped_at` = partida, `promised_at` = chegada prevista,
-- `delivered_at` = chegada real. Tarde é `delivered_at` depois de
-- `promised_at` mais a tolerância do cliente — a mesma conta dos
-- painéis, que a fazem pela viagem.
--
-- Anuláveis porque o ALTER corre sobre a tabela de produção já cheia,
-- antes do TRUNCATE. O INSERT preenche-as sempre.
ALTER TABLE freight.shipments ADD COLUMN IF NOT EXISTS shipped_at   TIMESTAMPTZ;
ALTER TABLE freight.shipments ADD COLUMN IF NOT EXISTS promised_at  TIMESTAMPTZ;
ALTER TABLE freight.shipments ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;

-- ── o gerador ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION pg_temp.u(VARIADIC k INT[]) RETURNS FLOAT8
LANGUAGE sql IMMUTABLE AS $$
    SELECT (hashtext('transportes:' || array_to_string(k, ':')) & 2147483647)::FLOAT8
           / 2147483648.0
$$;

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE freight.shipments, ops.trips, freight.clients, ops.routes,
         fleet.maintenance_jobs, fleet.drivers, fleet.vehicles
    RESTART IDENTITY CASCADE;

-- 18 viaturas. As três mais velhas (2014/2015) são onde tudo acontece:
-- gastam mais gasóleo, param mais vezes, e continuam a ser escaladas
-- porque "já estão pagas". Uma frota uniforme não tem história.
--
-- As matrículas, os modelos, as classes e os anos são os de sempre — são
-- o que os painéis e as respostas mostram. O custo fixo passa a depender
-- da classe (uma ligeira não paga o leasing de um tractor frigorífico) e
-- varia um pouco de viatura para viatura, como os contratos.
INSERT INTO fleet.vehicles (plate, model, class, acquired_on, capacity_kg, fixed_cost_month)
SELECT
    LPAD(g::TEXT, 2, '0') || '-'
        || (ARRAY['AB','CD','EF','GH','IJ','KL','MN','OP','QR'])[1 + g % 9]
        || '-' || LPAD((10 + g * 3)::TEXT, 2, '0'),
    (ARRAY['Volvo FH','Scania R450','MAN TGX','Mercedes Actros','Renault T','Iveco S-Way'])[1 + g % 6],
    (ARRAY['semi-reboque','semi-reboque','frigorífico','ligeiro'])[1 + g % 4],
    CASE WHEN g IN (3, 9, 14) THEN DATE '2014-06-01' + (g * 40)
         ELSE DATE '2021-01-01' + (g * 55) END,
    (ARRAY[24000, 24000, 18000, 3500])[1 + g % 4],
    -- As velhas já não têm leasing. É exactamente esse número baixo que
    -- faz parecer que compensa mantê-las.
    ROUND((CASE
        WHEN g IN (3, 9, 14) THEN 410
        ELSE (ARRAY[1180, 1180, 1360, 720])[1 + g % 4]
     END * (0.95 + 0.10 * pg_temp.u(g, 1)))::NUMERIC, 2)
FROM generate_series(1, 18) g;

INSERT INTO fleet.drivers (name, licence, hired_on, cost_per_hour)
SELECT
    (ARRAY['António Caldeira','Bruno Esteves','Carlos Pinheiro','David Marques',
           'Eduardo Vilela','Fernando Brito','Gonçalo Teixeira','Hélder Pacheco',
           'Ivo Rodrigues','Jorge Amaral','Luís Carvalho','Manuel Seabra',
           'Nuno Figueiredo','Octávio Reis','Paulo Tavares','Joaquim Barata',
           'Rui Gonçalves','Sérgio Monteiro','Tomás Varela','Vítor Lourenço',
           'Alberto Sousa','Bento Leal','Cláudio Neves','Diogo Pereira'])[g],
    (ARRAY['C+E','C+E','C','C+E'])[1 + g % 4],
    (DATE '2018-01-01' + (g * 97))::DATE,
    (14 + (g * 3) % 7)::NUMERIC(6,2)
FROM generate_series(1, 24) g;

-- 20 rotas na faixa ibérica onde esta operação vive: Lisboa e Porto a
-- Badajoz, Mérida, Almendralejo, Sevilla e Madrid.
--
-- ⚠️ As distâncias são escritas à mão, não geradas. A primeira versão
-- deste ficheiro calculava-as por fórmula e saía com Porto–Lisboa a
-- 453 km e o mesmo par de cidades com duas distâncias diferentes. Quem
-- trabalha em tráfego sabe estas distâncias de cor: um número errado
-- aqui não é um detalhe da demonstração, é o momento em que o prospect
-- deixa de acreditar em tudo o resto que está no ecrã.
--
-- A distância e o tempo padrão são o contrato implícito — é contra eles
-- que se mede se a viagem correu bem.
INSERT INTO ops.routes (origin, destination, distance_km, standard_minutes, toll_cost)
SELECT
    r.origem,
    r.destino,
    r.km,
    -- 72 km/h de média mais 45 min de carga e descarga. É optimista de
    -- propósito: um padrão que ninguém falha não mede nada.
    (r.km * 60 / 72 + 45)::INT,
    -- Portagem = só os km PAGOS em Portugal × 0,18 €/km (ordem de grandeza
    -- da classe 4, pesado de 4+ eixos). Em Espanha a A-5, a A-66 e a A-62
    -- são autovías do Estado, sem portagem: as rotas inteiramente
    -- espanholas pagam 0 €. A A23, a A24 e a A25 são ex-SCUT, livres
    -- desde 01/01/2025 (Lei n.º 37/2024).
    --
    -- A primeira versão fazia km × 0,072 para TODAS as rotas, e
    -- Badajoz–Madrid pela A-5 aparecia com 28,80 € de portagem. Um
    -- transportista da Extremadura vê isso no primeiro minuto.
    (r.km_pagos_pt * 0.18)::NUMERIC(8,2)
FROM (VALUES
    ( 1, 'Lisboa',       'Badajoz',      230, 220),
    ( 2, 'Lisboa',       'Porto',        315, 300),
    ( 3, 'Badajoz',      'Mérida',        65,   0),
    -- A 4 e a 11 são as duas ligações longas a Madrid. São elas que
    -- chegam sistematicamente fora do tempo padrão, mais abaixo.
    ( 4, 'Lisboa',       'Madrid',       625, 220),
    ( 5, 'Porto',        'Braga',         55,  50),
    ( 6, 'Badajoz',      'Sevilla',      220,   0),
    ( 7, 'Mérida',       'Almendralejo',  30,   0),
    ( 8, 'Lisboa',       'Sevilla',      460, 220),
    ( 9, 'Porto',        'Coimbra',      120, 115),
    (10, 'Almendralejo', 'Sevilla',      170,   0),
    (11, 'Porto',        'Madrid',       560,  70),
    (12, 'Coimbra',      'Lisboa',       200, 195),
    (13, 'Badajoz',      'Almendralejo',  55,   0),
    (14, 'Mérida',       'Sevilla',      195,   0),
    (15, 'Porto',        'Viseu',        130,  50),
    (16, 'Badajoz',      'Madrid',       400,   0),
    (17, 'Braga',        'Coimbra',      175, 170),
    (18, 'Lisboa',       'Mérida',       300, 220),
    (19, 'Porto',        'Badajoz',      400, 190),
    (20, 'Coimbra',      'Badajoz',      310,  60)
) AS r(ord, origem, destino, km, km_pagos_pt)
ORDER BY r.ord;

INSERT INTO freight.clients (name, sector, sla_minutes)
SELECT
    (ARRAY['Hortofrutícola Guadiana','Cerâmica do Tejo','Vinhos Alentejanos',
           'Metalúrgica Douro','Papel Ibérico','Frio Atlântico','Bebidas Centro',
           'Têxtil Minho','Químicos Sado','Mobiliário Serra','Rações do Sul',
           'Conservas Costa'])[g],
    (ARRAY['alimentar','construção','bebidas','metalurgia','papel','alimentar',
           'bebidas','têxtil','química','madeira','agropecuária','alimentar'])[g],
    -- O frio e o alimentar têm tolerância curta; a construção aceita
    -- meio dia. É por isso que o mesmo atraso custa coisas diferentes.
    (ARRAY[30, 240, 60, 180, 240, 30, 60, 180, 120, 240, 120, 30])[g]
FROM generate_series(1, 12) g;

-- ── A oficina ────────────────────────────────────────────────────
--
-- Primeiro a oficina, porque decide os dias em que a viatura NÃO sai.
-- A preventiva é previsível (de três em três meses); os pneus vêm com
-- os quilómetros; a avaria é o que estraga a semana — e concentra-se
-- nas três viaturas velhas, que também são as que mais dias passam
-- fora da estrada.
--
-- ⚠️ O custo depende da VIATURA, não só do `g`. Sem o `v.id` na conta,
-- as intervenções de cada viatura custavam exactamente o mesmo que as
-- da viatura ao lado: três camiões a 26.331 € e 35 dias parados, ao
-- euro e ao dia.
INSERT INTO fleet.maintenance_jobs (vehicle_id, done_on, kind, cost, days_off_road)
SELECT vehicle_id, done_on, kind, cost, days_off_road
FROM (
    -- preventiva: 4 por ano, com folga de uns dias
    SELECT v.id AS vehicle_id,
           (CURRENT_DATE - (g * 91 - 60 + (pg_temp.u(v.id, g, 10) * 40)::INT))::DATE AS done_on,
           'preventiva' AS kind,
           ROUND((CASE WHEN v.class = 'ligeiro' THEN 180 ELSE 310 END
                  + pg_temp.u(v.id, g, 11) * 280)::NUMERIC, 2) AS cost,
           CASE WHEN pg_temp.u(v.id, g, 12) < 0.2 THEN 1 ELSE 0 END AS days_off_road
    FROM fleet.vehicles v CROSS JOIN generate_series(1, 4) g
    UNION ALL
    -- pneus: 1 a 3 por ano
    SELECT v.id,
           (CURRENT_DATE - (5 + pg_temp.u(v.id, g, 20) * 355)::INT)::DATE,
           'pneus',
           ROUND((CASE WHEN v.class = 'ligeiro' THEN 260 ELSE 620 END
                  + pg_temp.u(v.id, g, 21) * 400)::NUMERIC, 2),
           0
    FROM fleet.vehicles v CROSS JOIN generate_series(1, 3) g
    WHERE g <= 1 + (pg_temp.u(v.id, 22) * 3)::INT
    UNION ALL
    -- avaria: as velhas 6 a 9 por ano; as outras 0 a 2
    SELECT v.id,
           (CURRENT_DATE - (3 + pg_temp.u(v.id, g, 30) * 357)::INT)::DATE,
           'avaria',
           ROUND((CASE WHEN v.id IN (3, 9, 14) THEN 1400 + pg_temp.u(v.id, g, 31) * 2600
                       ELSE 450 + pg_temp.u(v.id, g, 31) * 1700 END)::NUMERIC, 2),
           CASE WHEN v.id IN (3, 9, 14) THEN 2 + (pg_temp.u(v.id, g, 32) * 6)::INT
                ELSE 1 + (pg_temp.u(v.id, g, 32) * 2)::INT END
    FROM fleet.vehicles v CROSS JOIN generate_series(1, 9) g
    WHERE g <= CASE WHEN v.id IN (3, 9, 14) THEN 6 + (pg_temp.u(v.id, 33) * 3.99)::INT
                    ELSE (pg_temp.u(v.id, 33) * 2.99)::INT END
) m
WHERE done_on < CURRENT_DATE
ORDER BY done_on, vehicle_id;

-- ── As viagens ───────────────────────────────────────────────────
--
-- Dia a dia, viatura a viatura, durante 365 dias até ontem. Sai ou não
-- sai conforme:
--   • a taxa de ocupação da viatura (62 % a 95 %; as velhas ~80 %, porque
--     "já estão pagas" e continuam a ser escaladas);
--   • o dia da semana (domingo quase parado, sábado a meio gás);
--   • o mês (Agosto cai; a vindima e a campanha de Outono sobem);
--   • a oficina: com dias fora da estrada não há viagem.
--
-- Cada viatura tem a sua base — Lisboa, Porto ou Badajoz — e prefere as
-- rotas que partem de lá. A ligeira faz trajectos curtos, e quando o
-- primeiro serviço é curto faz um segundo no mesmo dia.
CREATE TEMP TABLE _v ON COMMIT DROP AS
SELECT
    v.id,
    v.class,
    v.capacity_kg,
    v.id IN (3, 9, 14) AS velha,
    CASE WHEN v.id IN (3, 9, 14) THEN 0.78 + 0.06 * pg_temp.u(v.id, 40)
         ELSE 0.62 + 0.33 * pg_temp.u(v.id, 40) END AS ocupacao,
    -- 1 = Lisboa/Coimbra, 2 = Porto/Braga, 3 = Extremadura
    1 + (v.id % 3) AS base
FROM fleet.vehicles v;

CREATE TEMP TABLE _r ON COMMIT DROP AS
SELECT r.*,
       CASE WHEN r.origin IN ('Lisboa', 'Coimbra') THEN 1
            WHEN r.origin IN ('Porto', 'Braga') THEN 2
            ELSE 3 END AS regiao
FROM ops.routes r;

CREATE TEMP TABLE _cumr ON COMMIT DROP AS
WITH w AS (
    SELECT v.id AS vid, r.id AS rid, r.distance_km AS km,
           (CASE WHEN r.regiao = v.base THEN 3.0 ELSE 1.0 END)
           * (CASE WHEN v.class = 'ligeiro'
                   THEN CASE WHEN r.distance_km <= 230 THEN 4.0 ELSE 0.15 END
                   ELSE CASE WHEN r.distance_km >= 300 THEN 1.4 ELSE 1.0 END END)
           -- e um gosto próprio de cada viatura, para as rotas não ficarem
           -- repartidas por igual
           * (0.5 + pg_temp.u(v.id, r.id, 41)) AS w
    FROM _v v CROSS JOIN _r r
)
SELECT vid, rid, km,
       COALESCE(SUM(w) OVER (PARTITION BY vid ORDER BY rid
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
           / SUM(w) OVER (PARTITION BY vid) AS lo,
       SUM(w) OVER (PARTITION BY vid ORDER BY rid) / SUM(w) OVER (PARTITION BY vid) AS hi,
       -- a mesma escolha, só entre as rotas curtas (o 2.º serviço do dia)
       COALESCE(SUM(CASE WHEN km <= 230 THEN w ELSE 0 END)
                    OVER (PARTITION BY vid ORDER BY rid
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
           / SUM(CASE WHEN km <= 230 THEN w ELSE 0 END) OVER (PARTITION BY vid) AS lo2,
       SUM(CASE WHEN km <= 230 THEN w ELSE 0 END) OVER (PARTITION BY vid ORDER BY rid)
           / SUM(CASE WHEN km <= 230 THEN w ELSE 0 END) OVER (PARTITION BY vid) AS hi2
FROM w;

CREATE TEMP TABLE _dia ON COMMIT DROP AS
SELECT v.id AS vid, d.d, (CURRENT_DATE - d.d) AS dia
FROM _v v
CROSS JOIN generate_series(1, 365) AS d(d)
WHERE pg_temp.u(v.id, d.d, 42) <
      v.ocupacao
      * (ARRAY[0.06, 1.00, 1.00, 1.00, 1.00, 0.95, 0.35])
          [1 + EXTRACT(DOW FROM CURRENT_DATE - d.d)::INT]
      * (ARRAY[0.90, 0.92, 1.00, 1.00, 1.02, 1.05, 1.00, 0.72, 1.10, 1.12, 1.05, 0.95])
          [EXTRACT(MONTH FROM CURRENT_DATE - d.d)::INT]
  AND NOT EXISTS (
      SELECT 1 FROM fleet.maintenance_jobs m
      WHERE m.vehicle_id = v.id AND m.days_off_road > 0
        AND (CURRENT_DATE - d.d) >= m.done_on
        AND (CURRENT_DATE - d.d) <  m.done_on + m.days_off_road
  );

CREATE TEMP TABLE _via ON COMMIT DROP AS
WITH primeiro AS (
    SELECT di.vid, di.d, di.dia, 1 AS n, c.rid, c.km,
           di.dia + ((5 * 60 + pg_temp.u(di.vid, di.d, 43) * 240)::INT) * INTERVAL '1 minute'
               AS partida
    FROM _dia di
    JOIN _cumr c ON c.vid = di.vid
     AND pg_temp.u(di.vid, di.d, 44) >= c.lo AND pg_temp.u(di.vid, di.d, 44) < c.hi
)
SELECT * FROM primeiro
UNION ALL
SELECT p.vid, p.d, p.dia, 2, c.rid, c.km,
       -- sai uma hora e pouco depois de o primeiro chegar
       p.partida + ((r.standard_minutes + 60 + pg_temp.u(p.vid, p.d, 45) * 45)::INT)
                   * INTERVAL '1 minute'
FROM primeiro p
JOIN _r r ON r.id = p.rid
JOIN _cumr c ON c.vid = p.vid AND c.km <= 230
 AND pg_temp.u(p.vid, p.d, 46) >= c.lo2 AND pg_temp.u(p.vid, p.d, 46) < c.hi2
WHERE p.km <= 230
  AND pg_temp.u(p.vid, p.d, 47) < (CASE WHEN p.km <= 130 THEN 0.70 ELSE 0.45 END);

CREATE TEMP TABLE _via2 ON COMMIT DROP AS
SELECT
    x.*,
    v.class, v.capacity_kg, v.velha,
    r.standard_minutes, r.destination,
    -- O atraso. As rotas 4 e 11 têm um estrangulamento que o tempo
    -- padrão nunca reconheceu: chegam tarde quase sempre. Nas outras a
    -- maioria chega a horas e uma em cada dez apanha um imprevisto. No
    -- Inverno e à sexta-feira piora um pouco.
    (CASE
        WHEN x.rid IN (4, 11) AND pg_temp.u(x.vid, x.d, x.n, 50) < 0.78
            THEN 60 + pg_temp.u(x.vid, x.d, x.n, 51) * 170
        WHEN pg_temp.u(x.vid, x.d, x.n, 50) < 0.10
            THEN 25 + pg_temp.u(x.vid, x.d, x.n, 51) * 110
        ELSE pg_temp.u(x.vid, x.d, x.n, 51) * 34 - 16
     END
     + CASE WHEN EXTRACT(MONTH FROM x.dia)::INT IN (12, 1, 2) THEN 9 ELSE 0 END
     + CASE WHEN EXTRACT(DOW FROM x.dia)::INT = 5 THEN 6 ELSE 0 END)::INT AS atraso,
    -- Retorno vazio: um em cada cinco, mais nos regressos de Madrid e de
    -- Sevilla (não há carga de volta) e no segundo serviço do dia.
    pg_temp.u(x.vid, x.d, x.n, 52) <
        CASE WHEN x.n = 2 THEN 0.30
             WHEN r.destination = 'Madrid' THEN 0.32
             WHEN r.destination = 'Sevilla' THEN 0.26
             ELSE 0.13 END AS vazio,
    -- Quem conduz: cada viatura tem o seu motorista; os seis de reserva
    -- cobrem folgas e férias.
    CASE WHEN pg_temp.u(x.vid, x.d, x.n, 53) < 0.84 THEN x.vid
         ELSE 19 + (pg_temp.u(x.vid, x.d, x.n, 54) * 6)::INT % 6 END AS driver_id,
    -- Quilómetros: a distância da rota mais os desvios do dia.
    (r.distance_km * (1.00 + 0.06 * pg_temp.u(x.vid, x.d, x.n, 55)))::INT AS km_run
FROM _via x
JOIN _v v ON v.id = x.vid
JOIN _r r ON r.id = x.rid;

INSERT INTO ops.trips (vehicle_id, driver_id, route_id, departed_at,
                       planned_arrival, arrived_at, km_run, fuel_litres,
                       driver_hours, status)
SELECT
    x.vid,
    x.driver_id,
    x.rid,
    x.partida,
    x.partida + x.standard_minutes * INTERVAL '1 minute',
    x.partida + (x.standard_minutes + x.atraso) * INTERVAL '1 minute',
    x.km_run,
    -- L/100 km: tractor 28, frigorífico 31 (o grupo de frio), ligeira 12.
    -- As velhas gastam um terço a mais. Vazio gasta menos.
    ROUND((x.km_run / 100.0
           * (CASE x.class WHEN 'ligeiro' THEN 12.0 WHEN 'frigorífico' THEN 31.0 ELSE 28.0 END)
           * (CASE WHEN x.velha THEN 1.34 ELSE 1.0 END)
           * (CASE WHEN x.vazio THEN 0.86 ELSE 1.0 END)
           * (0.96 + 0.08 * pg_temp.u(x.vid, x.d, x.n, 56)))::NUMERIC, 2),
    ROUND(((x.standard_minutes + x.atraso) / 60.0)::NUMERIC, 2),
    CASE WHEN pg_temp.u(x.vid, x.d, x.n, 57) < 0.01 THEN 'cancelled' ELSE 'completed' END
FROM _via2 x
WHERE x.partida + (x.standard_minutes + x.atraso) * INTERVAL '1 minute' < now()
ORDER BY x.partida, x.vid;

-- ── A carga ──────────────────────────────────────────────────────
--
-- Um porte por viagem carregada. O cliente escolhe-se pelo seu peso na
-- carteira (há clientes grandes e pequenos), pela região da rota (um
-- cliente do Minho não carrega em Mérida), pela classe (o frio vai no
-- frigorífico) e pela estação (o vinho no Outono, a fruta no Verão, as
-- bebidas em Julho e Agosto).
CREATE TEMP TABLE _cumc ON COMMIT DROP AS
WITH cli AS (
    SELECT * FROM (VALUES
        -- id, peso, região de origem (1 Lisboa, 2 Porto, 3 Extremadura), é frio
        ( 1, 1.60, 3, TRUE),   -- Hortofrutícola Guadiana
        ( 2, 0.80, 1, FALSE),  -- Cerâmica do Tejo
        ( 3, 1.40, 1, FALSE),  -- Vinhos Alentejanos
        ( 4, 1.00, 2, FALSE),  -- Metalúrgica Douro
        ( 5, 0.90, 3, FALSE),  -- Papel Ibérico
        ( 6, 0.90, 1, TRUE),   -- Frio Atlântico
        ( 7, 0.70, 1, FALSE),  -- Bebidas Centro
        ( 8, 0.60, 2, FALSE),  -- Têxtil Minho
        ( 9, 0.50, 1, FALSE),  -- Químicos Sado
        (10, 0.45, 2, FALSE),  -- Mobiliário Serra
        (11, 0.80, 3, FALSE),  -- Rações do Sul
        (12, 0.55, 2, TRUE)    -- Conservas Costa
    ) AS c(id, peso, regiao, frio)
), w AS (
    SELECT reg.r AS regiao, f.frigo, m.mes, c.id AS cid,
           c.peso
           * (CASE WHEN c.regiao = reg.r THEN 3.0 ELSE 0.7 END)
           * (CASE WHEN f.frigo = c.frio THEN 1.0 WHEN f.frigo THEN 0.25 ELSE 0.35 END)
           * (CASE
                 WHEN c.id = 3 THEN (ARRAY[0.8,0.8,0.8,0.8,0.8,0.8,0.9,1.0,1.6,1.7,1.5,1.4])[m.mes]
                 WHEN c.id = 1 THEN (ARRAY[0.7,0.7,0.8,1.0,1.4,1.6,1.6,1.5,1.3,0.9,0.7,0.7])[m.mes]
                 WHEN c.id = 7 THEN (ARRAY[0.7,0.7,0.8,0.9,1.1,1.5,1.7,1.6,1.0,0.8,0.8,1.1])[m.mes]
                 ELSE 1.0
              END) AS w
    FROM cli c
    CROSS JOIN generate_series(1, 3) AS reg(r)
    CROSS JOIN (VALUES (TRUE), (FALSE)) AS f(frigo)
    CROSS JOIN generate_series(1, 12) AS m(mes)
)
SELECT regiao, frigo, mes, cid,
       COALESCE(SUM(w) OVER (PARTITION BY regiao, frigo, mes ORDER BY cid
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
           / SUM(w) OVER (PARTITION BY regiao, frigo, mes) AS lo,
       SUM(w) OVER (PARTITION BY regiao, frigo, mes ORDER BY cid)
           / SUM(w) OVER (PARTITION BY regiao, frigo, mes) AS hi
FROM w;

-- O preço do porte: uma parte fixa de movimentação e uma parte por
-- quilómetro que sobe com o peso. A parte fixa é o que torna a tarifa
-- degressiva — um porte de 30 km sai a vários euros por quilómetro e um
-- de 600 km sai a pouco mais de 1,50 €, que é como esta indústria cobra.
-- A ligeira cobra menos por quilómetro e menos de fixo: é outra tabela.
--
-- E a tarifa negociada de cada cliente (quinze por cento para cada lado):
-- sem ela os doze clientes davam o mesmo euro por quilómetro, e a
-- pergunta «¿qué clientes dejan más por kilómetro?» respondia com doze
-- números iguais.
--
-- O peso nunca passa a capacidade da viatura — uma ligeira de 3.500 kg
-- com 15 toneladas era o tipo de linha que um director de tráfego lê
-- primeiro.
INSERT INTO freight.shipments (trip_id, client_id, weight_kg, pallets, revenue, incident,
                               shipped_at, promised_at, delivered_at)
SELECT
    t.id,
    cc.cid,
    peso.kg,
    LEAST(CASE WHEN v.class = 'ligeiro' THEN 8 ELSE 33 END,
          GREATEST(1, CEIL(peso.kg / 700.0)::INT)),
    ROUND((
        CASE WHEN v.class = 'ligeiro'
             THEN 45 + t.km_run * (0.78 + peso.kg * 0.00008)
             ELSE (120 + t.km_run * (1.02 + peso.kg * 0.000026))
                  * CASE WHEN v.class = 'frigorífico' THEN 1.10 ELSE 1.0 END
        END
        * (ARRAY[0.86, 0.90, 0.94, 0.97, 0.99, 1.01,
                 1.03, 1.06, 1.09, 1.13, 1.18, 1.25])[cc.cid]
    )::NUMERIC, 2),
    CASE
        -- A cerâmica parte-se: concentra os danos, e é isso que o agente
        -- de incidências tem de encontrar.
        WHEN pg_temp.u(t.id, 60) < CASE WHEN cc.cid = 2 THEN 0.05 ELSE 0.011 END
            THEN 'mercadoria danificada'
        WHEN v.class = 'frigorífico' AND pg_temp.u(t.id, 61) < 0.025
            THEN 'falha de temperatura'
        WHEN pg_temp.u(t.id, 62) < 0.007
            THEN 'documentação em falta'
        ELSE NULL
    END,
    t.departed_at,
    t.planned_arrival,
    t.arrived_at
FROM ops.trips t
JOIN _v v ON v.id = t.vehicle_id
JOIN _r r ON r.id = t.route_id
JOIN _via2 x ON x.vid = t.vehicle_id AND x.partida = t.departed_at
JOIN _cumc cc
  ON cc.regiao = r.regiao
 AND cc.frigo = (v.class = 'frigorífico')
 AND cc.mes = EXTRACT(MONTH FROM t.departed_at)::INT
 AND pg_temp.u(t.id, 63) >= cc.lo AND pg_temp.u(t.id, 63) < cc.hi
CROSS JOIN LATERAL (
    SELECT (v.capacity_kg * (0.35 + 0.60 * pg_temp.u(t.id, 64)))::INT AS kg
) peso
WHERE t.status = 'completed'
  AND NOT x.vazio
ORDER BY t.id;

CREATE INDEX IF NOT EXISTS idx_trips_vehicle ON ops.trips(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_trips_route ON ops.trips(route_id);
CREATE INDEX IF NOT EXISTS idx_trips_driver ON ops.trips(driver_id);
CREATE INDEX IF NOT EXISTS idx_trips_departed ON ops.trips(departed_at);
CREATE INDEX IF NOT EXISTS idx_ship_trip ON freight.shipments(trip_id);
CREATE INDEX IF NOT EXISTS idx_ship_client ON freight.shipments(client_id);
CREATE INDEX IF NOT EXISTS idx_ship_shipped ON freight.shipments(shipped_at);
CREATE INDEX IF NOT EXISTS idx_maint_vehicle ON fleet.maintenance_jobs(vehicle_id);

ANALYZE fleet.vehicles;
ANALYZE fleet.maintenance_jobs;
ANALYZE ops.trips;
ANALYZE freight.shipments;

COMMIT;
