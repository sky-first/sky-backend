-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Indústria / Produção
-- ─────────────────────────────────────────────────────────────────
-- Numa fábrica os dados existem todos, e em sistemas diferentes: o
-- MES sabe o que a máquina produziu, a qualidade sabe o que foi
-- rejeitado, a manutenção sabe porque é que parou, e o turno sabe
-- quem lá estava. Ninguém junta os quatro — e é da junção que saem as
-- únicas três perguntas que mudam alguma coisa:
--
--   • que máquina está a fazer a maior parte do refugo;
--   • quanto tempo se perdeu em paragens não planeadas, e porquê;
--   • que turno produz menos com o mesmo equipamento.
--
--   plant.machines            — linha, ano, capacidade nominal
--   production.orders         — ordem, máquina, turno, quantidades
--   quality.scrap             — o que foi rejeitado, e o motivo
--   maintenance.stoppages     — quanto tempo parou, e porquê
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS plant;
CREATE SCHEMA IF NOT EXISTS production;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS maintenance;

CREATE TABLE IF NOT EXISTS plant.machines (
    id            SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    line          TEXT NOT NULL,
    installed_year INT NOT NULL,
    nominal_rate  INT NOT NULL      -- unidades por hora
);

CREATE TABLE IF NOT EXISTS production.orders (
    id            SERIAL PRIMARY KEY,
    machine_id    INT NOT NULL REFERENCES plant.machines(id),
    shift         TEXT NOT NULL,
    produced_on   DATE NOT NULL,
    planned_units INT NOT NULL,
    good_units    INT NOT NULL,
    run_hours     NUMERIC(6,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS quality.scrap (
    id         SERIAL PRIMARY KEY,
    order_id   INT NOT NULL REFERENCES production.orders(id),
    reason     TEXT NOT NULL,
    units      INT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance.stoppages (
    id          SERIAL PRIMARY KEY,
    machine_id  INT NOT NULL REFERENCES plant.machines(id),
    started_at  TIMESTAMPTZ NOT NULL,
    minutes     INT NOT NULL,
    planned     BOOLEAN NOT NULL,
    reason      TEXT NOT NULL
);

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE maintenance.stoppages, quality.scrap, production.orders, plant.machines
    RESTART IDENTITY CASCADE;

-- 9 máquinas em três linhas. A M-07 é a mais velha — e é onde tudo
-- acontece. Uma fábrica com equipamento uniforme não tem história.
INSERT INTO plant.machines (code, line, installed_year, nominal_rate)
SELECT
    'M-' || LPAD(g::TEXT, 2, '0'),
    (ARRAY['Linha A','Linha A','Linha A','Linha B','Linha B','Linha B',
           'Linha C','Linha C','Linha C'])[g],
    (ARRAY[2019, 2021, 2020, 2018, 2022, 2021, 2006, 2020, 2019])[g],
    (ARRAY[420, 380, 400, 520, 500, 480, 300, 350, 360])[g]
FROM generate_series(1, 9) g;

-- 12 meses de ordens de produção, três turnos por dia.
--
-- O turno da noite produz menos com o mesmo equipamento — e a M-07
-- produz menos do que devia em qualquer turno.
INSERT INTO production.orders (machine_id, shift, produced_on, planned_units, good_units, run_hours)
SELECT
    m.id,
    (ARRAY['manhã','tarde','noite'])[1 + g % 3],
    (CURRENT_DATE - INTERVAL '12 months' + ((g * 2 + m.id) % 360) * INTERVAL '1 day')::DATE,
    planned.units,
    -- Bom = planeado menos refugo. A M-07 rejeita muito mais, e a noite
    -- rende menos em todas as máquinas.
    GREATEST(
        0,
        (planned.units
         - CASE WHEN m.id = 7 THEN (planned.units * 0.11)::INT ELSE (planned.units * 0.015)::INT END
         - CASE WHEN (1 + g % 3) = 3 THEN (planned.units * 0.06)::INT ELSE 0 END
        )::INT
    ),
    (6 + (g + m.id) % 3)::NUMERIC(6,2)
FROM plant.machines m
CROSS JOIN generate_series(1, 55) g
CROSS JOIN LATERAL (SELECT (m.nominal_rate * (6 + (g + m.id) % 3))::INT AS units) planned;

-- Refugo, com motivo. Um motivo domina numa máquina só — que é a
-- diferença entre "temos um problema de qualidade" e "temos um
-- problema na M-07".
INSERT INTO quality.scrap (order_id, reason, units)
SELECT
    o.id,
    CASE
        WHEN o.machine_id = 7 THEN 'desalinhamento'
        ELSE (ARRAY['material','ajuste','operador','embalagem'])[1 + o.id % 4]
    END,
    GREATEST(1, o.planned_units - o.good_units)
FROM production.orders o
WHERE o.planned_units > o.good_units;

-- Paragens. As planeadas são manutenção preventiva; as não planeadas
-- são o que custa dinheiro — e concentram-se na máquina de 2006.
INSERT INTO maintenance.stoppages (machine_id, started_at, minutes, planned, reason)
SELECT
    m.id,
    (CURRENT_DATE - INTERVAL '12 months' + ((g * 7 + m.id) % 360) * INTERVAL '1 day')::TIMESTAMPTZ
        + ((g % 8) * INTERVAL '1 hour'),
    CASE
        WHEN m.id = 7 AND g % 3 <> 0 THEN 45 + (g * 13) % 180
        WHEN g % 4 = 0 THEN 60 + (g * 7) % 60          -- preventiva
        ELSE 10 + (g * 11) % 40
    END,
    (g % 4 = 0),
    CASE
        WHEN g % 4 = 0 THEN 'manutenção preventiva'
        WHEN m.id = 7 THEN 'avaria mecânica'
        ELSE (ARRAY['mudança de formato','falta de material','ajuste de qualidade',
                    'avaria eléctrica'])[1 + g % 4]
    END
FROM plant.machines m
CROSS JOIN generate_series(1, 28) g;

CREATE INDEX IF NOT EXISTS idx_orders_machine ON production.orders(machine_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON production.orders(produced_on);
CREATE INDEX IF NOT EXISTS idx_scrap_order ON quality.scrap(order_id);
CREATE INDEX IF NOT EXISTS idx_stop_machine ON maintenance.stoppages(machine_id);

COMMIT;
