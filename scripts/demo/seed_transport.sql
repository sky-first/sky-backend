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
--   freight.shipments        — a carga que seguiu, e por quanto
--
-- ── Os números não são de ninguém ────────────────────────────────
--
-- Os dados são sintéticos e gerados por fórmula. Não vêm de nenhum
-- cliente e não descrevem nenhuma operação real — o que se demonstra
-- é a pergunta, não a empresa.
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

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE freight.shipments, ops.trips, freight.clients, ops.routes,
         fleet.maintenance_jobs, fleet.drivers, fleet.vehicles
    RESTART IDENTITY CASCADE;

-- 18 viaturas. As três mais velhas (2014/2015) são onde tudo acontece:
-- gastam mais gasóleo, param mais vezes, e continuam a ser escaladas
-- porque "já estão pagas". Uma frota uniforme não tem história.
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
    CASE WHEN g IN (3, 9, 14) THEN 410.00 ELSE 1180.00 END
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
    (r.km * 0.072)::NUMERIC(8,2)
FROM (VALUES
    ( 1, 'Lisboa',       'Badajoz',      230),
    ( 2, 'Lisboa',       'Porto',        315),
    ( 3, 'Badajoz',      'Mérida',        65),
    -- A 4 e a 11 são as duas ligações longas a Madrid. São elas que
    -- chegam sistematicamente fora do tempo padrão, mais abaixo.
    ( 4, 'Lisboa',       'Madrid',       625),
    ( 5, 'Porto',        'Braga',         55),
    ( 6, 'Badajoz',      'Sevilla',      220),
    ( 7, 'Mérida',       'Almendralejo',  30),
    ( 8, 'Lisboa',       'Sevilla',      460),
    ( 9, 'Porto',        'Coimbra',      120),
    (10, 'Almendralejo', 'Sevilla',      170),
    (11, 'Porto',        'Madrid',       560),
    (12, 'Coimbra',      'Lisboa',       200),
    (13, 'Badajoz',      'Almendralejo',  55),
    (14, 'Mérida',       'Sevilla',      195),
    (15, 'Porto',        'Viseu',        130),
    (16, 'Badajoz',      'Madrid',       400),
    (17, 'Braga',        'Coimbra',      175),
    (18, 'Lisboa',       'Mérida',       300),
    (19, 'Porto',        'Badajoz',      400),
    (20, 'Coimbra',      'Badajoz',      310)
) AS r(ord, origem, destino, km)
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

-- 12 meses de viagens: 18 viaturas x 280 = 5.040. Com um percurso
-- medio de 250 km da-se ~70.000 km/ano por viatura, que e a ordem
-- de grandeza de uma operacao regional a serio.
--
-- Quatro coisas plantadas de propósito, porque são as quatro que fazem
-- a conversa com um director de operações:
--
--   • as viaturas 3, 9 e 14 gastam ~34% mais gasóleo por quilómetro;
--   • ~1 em cada 5 viagens é retorno vazio — sem carga, sem receita;
--   • as rotas 4 e 11 chegam sistematicamente fora do tempo padrão;
--   • o atraso médio das restantes é pequeno, para que as duas se vejam.
INSERT INTO ops.trips (vehicle_id, driver_id, route_id, departed_at,
                       planned_arrival, arrived_at, km_run, fuel_litres,
                       driver_hours, status)
SELECT
    v.id,
    1 + (g * 7 + v.id) % 24,
    r.id,
    partida.ts,
    partida.ts + (r.standard_minutes * INTERVAL '1 minute'),
    partida.ts + ((r.standard_minutes + atraso.min) * INTERVAL '1 minute'),
    r.distance_km,
    -- 28 L/100 km de base; as três velhas fazem 37,5.
    (r.distance_km * CASE WHEN v.id IN (3, 9, 14) THEN 0.375 ELSE 0.280 END)::NUMERIC(8,2),
    ((r.standard_minutes + atraso.min) / 60.0)::NUMERIC(6,2),
    CASE WHEN (g * 11 + v.id) % 97 = 0 THEN 'cancelled' ELSE 'completed' END
FROM fleet.vehicles v
CROSS JOIN generate_series(1, 280) g
CROSS JOIN LATERAL (SELECT 1 + (g * 13 + v.id * 5) % 20 AS rid) escolha
JOIN ops.routes r ON r.id = escolha.rid
CROSS JOIN LATERAL (
    SELECT (CURRENT_DATE - INTERVAL '12 months'
            + ((g * 2 + v.id * 3) % 360) * INTERVAL '1 day'
            + ((g % 11) * INTERVAL '1 hour'))::TIMESTAMPTZ AS ts
) partida
CROSS JOIN LATERAL (
    SELECT CASE
        -- As rotas 4 e 11 têm um estrangulamento que o tempo padrão
        -- nunca reconheceu: chegam tarde quase sempre.
        WHEN escolha.rid IN (4, 11) THEN 95 + (g * 17) % 120
        WHEN (g + v.id) % 7 = 0     THEN 40 + (g * 7) % 90
        ELSE (g * 3) % 25 - 12
    END AS min
) atraso;

-- A carga. ~20% das viagens seguem sem carga nenhuma — é o retorno
-- vazio, e é o custo mais invisível desta indústria: aparece todo no
-- gasóleo e nunca aparece na faturação.
--
-- O preço do porte é por quilómetro e por tonelada, com um mínimo. Não
-- é a tabela de ninguém; é a forma de a margem variar por cliente.
--
-- O preço tem uma parte fixa de movimentação e uma parte por
-- quilómetro que sobe com o peso. A parte fixa é o que torna a tarifa
-- degressiva — um porte de 30 km sai a vários euros por quilómetro e um
-- de 600 km sai a pouco mais de 1,50 €, que é como esta indústria
-- cobra mesmo.
--
-- ⚠️ A primeira versão usava `GREATEST(280, …)` em vez da parte fixa, e
-- esse mínimo disparava numa viagem em cada três: metade das rotas tem
-- menos de 200 km. Era o mínimo a fazer o preço, não os dados — e num
-- ecrã cuja tese é "os teus números estão aqui", um preço que não
-- depende dos números é a pior coisa que lá pode estar.
--
-- Os coeficientes estão calibrados para a receita por quilómetro ficar
-- acima do custo de uma viatura recente (~1,15 €) e abaixo do de uma
-- velha (~1,45 €). Sem essa calibração o sector não tem história
-- nenhuma: ou todas as viaturas dão lucro, ou nenhuma dá.
--
-- ⚠️ O cliente e o peso saem de um `hashint4`, não de `id % n`. Com o
-- resto simples davam um enviesamento por viatura: as viagens são
-- inseridas viatura a viatura, logo os `id` de cada uma são um bloco
-- contíguo, e um multiplicador pequeno faz esse bloco cair sempre na
-- mesma zona da gama. O resultado era a receita por quilómetro a
-- depender de QUAL é o camião — duas viaturas velhas apareciam
-- lucrativas só porque lhes calhava carga mais pesada. Numa demo de
-- rentabilidade de frota, é precisamente o número que não pode mentir.
INSERT INTO freight.shipments (trip_id, client_id, weight_kg, pallets, revenue, incident)
SELECT
    t.id,
    1 + (ABS(hashint4(t.id)) % 12),
    peso.kg,
    GREATEST(1, peso.kg / 800),
    -- ⚠️ Sem a tarifa por cliente, todos rendem o mesmo por quilómetro.
    --
    -- A receita saía só dos quilómetros e do peso, e o peso é aleatório
    -- por viagem — independente do cliente. Resultado: os doze clientes
    -- davam entre 1,81 e 1,88 €/km, quatro por cento de diferença entre
    -- o melhor e o pior. A pergunta «que clientes dejan más por
    -- kilómetro?» respondia com seis números iguais e uma conclusão
    -- vazia, que é pior do que não ter a pergunta.
    --
    -- Num transportador real a tarifa é negociada, e é essa negociação
    -- que decide quem paga o camião. Quinze por cento para cada lado
    -- não é exagero: é o que separa um contrato antigo de um recente.
    (120 + t.km_run * (1.05 + peso.kg * 0.000028) * tarifa.m)::NUMERIC(10,2),
    CASE
        WHEN t.id % 53 = 0 THEN 'mercadoria danificada'
        WHEN t.id % 71 = 0 THEN 'falha de temperatura'
        WHEN t.id % 89 = 0 THEN 'documentação em falta'
        ELSE NULL
    END
FROM ops.trips t
CROSS JOIN LATERAL (SELECT (4200 + ABS(hashint4(t.id * 31)) % 15000)::INT AS kg) peso
CROSS JOIN LATERAL (
    SELECT (ARRAY[0.86, 0.90, 0.94, 0.97, 0.99, 1.01,
                  1.03, 1.06, 1.09, 1.13, 1.18, 1.25])[
        1 + (ABS(hashint4(t.id)) % 12)
    ] AS m
) tarifa
WHERE t.status = 'completed'
  -- O retorno vazio, ~20%, de propósito.
  --
  -- ⚠️ Pelo `t.id % 5` as viagens vazias caíam sempre nas mesmas rotas:
  -- as viagens são inseridas viatura a viatura e a rota também sai de
  -- uma progressão, por isso os dois restos entravam em fase. A fracção
  -- de quilómetros carregados variava de 72% a 87% consoante a viatura,
  -- e isso sozinho decidia quais pareciam rentáveis. O hash quebra a
  -- fase: o vazio passa a cair em todas as rotas por igual.
  AND ABS(hashint4(t.id * 97)) % 5 <> 0;

-- Oficina. A preventiva é previsível; a avaria é o que estraga a
-- semana — e concentra-se nas três viaturas velhas, que também são as
-- que mais dias passam fora da estrada.
INSERT INTO fleet.maintenance_jobs (vehicle_id, done_on, kind, cost, days_off_road)
SELECT
    v.id,
    (CURRENT_DATE - INTERVAL '12 months' + ((g * 29 + v.id * 11) % 360) * INTERVAL '1 day')::DATE,
    CASE
        WHEN v.id IN (3, 9, 14) AND g % 3 <> 0 THEN 'avaria'
        WHEN g % 4 = 0 THEN 'pneus'
        ELSE 'preventiva'
    END,
    -- ⚠️ O custo tem de depender da VIATURA, não só do `g`.
    --
    -- Sem o `v.id` na conta, as catorze intervenções de cada viatura
    -- custavam exactamente o mesmo que as da viatura ao lado: três
    -- camiões a 26.331 € e 35 dias parados, ao euro e ao dia. Numa
    -- tabela de oficina isso é a coisa mais visível a dizer «dados
    -- inventados» — e é a tabela que um director de frota lê primeiro.
    (CASE
        WHEN v.id IN (3, 9, 14) AND g % 3 <> 0
            THEN 1400 + ABS(hashint4(v.id * 977 + g * 137)) % 2600
        WHEN g % 4 = 0 THEN 620 + ABS(hashint4(v.id * 613 + g * 41)) % 400
        ELSE 310 + ABS(hashint4(v.id * 419 + g * 23)) % 280
     END)::NUMERIC(10,2),
    CASE
        WHEN v.id IN (3, 9, 14) AND g % 3 <> 0
            THEN 2 + ABS(hashint4(v.id * 251 + g * 3)) % 6
        ELSE 0
    END
FROM fleet.vehicles v
CROSS JOIN generate_series(1, 14) g;

CREATE INDEX IF NOT EXISTS idx_trips_vehicle ON ops.trips(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_trips_route ON ops.trips(route_id);
CREATE INDEX IF NOT EXISTS idx_trips_driver ON ops.trips(driver_id);
CREATE INDEX IF NOT EXISTS idx_trips_departed ON ops.trips(departed_at);
CREATE INDEX IF NOT EXISTS idx_ship_trip ON freight.shipments(trip_id);
CREATE INDEX IF NOT EXISTS idx_ship_client ON freight.shipments(client_id);
CREATE INDEX IF NOT EXISTS idx_maint_vehicle ON fleet.maintenance_jobs(vehicle_id);

COMMIT;
