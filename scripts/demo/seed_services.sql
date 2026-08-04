-- ─────────────────────────────────────────────────────────────────
-- Dados de demonstração — Serviços / Consultoria
-- ─────────────────────────────────────────────────────────────────
-- Num negócio de serviços o produto são horas, e as três perguntas que
-- ninguém consegue responder de cabeça são sempre as mesmas:
--
--   • quanto da capacidade que pago é que chega a ser faturável;
--   • que projectos já gastaram mais horas do que venderam;
--   • quanto trabalho está feito e por faturar.
--
-- Nenhuma delas se responde num sistema só: as horas estão no
-- registo de tempos, o preço está no contrato, e a fatura está na
-- contabilidade. É a junção que dá a resposta — e é a junção que
-- ninguém faz todas as semanas.
--
--   people.consultants     — custo, capacidade contratada
--   delivery.projects      — cliente, tipo de contrato, horas vendidas
--   delivery.time_entries  — quem, quando, quanto, faturável ou não
--   billing.invoices       — o que foi efectivamente faturado
--
-- Re-executável: TRUNCATE antes de cada INSERT.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS people;
CREATE SCHEMA IF NOT EXISTS delivery;
CREATE SCHEMA IF NOT EXISTS billing;

CREATE TABLE IF NOT EXISTS people.consultants (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    grade          TEXT NOT NULL,
    cost_per_hour  NUMERIC(8,2) NOT NULL,
    weekly_capacity INT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing.clients (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    industry TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery.projects (
    id            SERIAL PRIMARY KEY,
    client_id     INT NOT NULL REFERENCES billing.clients(id),
    name          TEXT NOT NULL,
    contract_type TEXT NOT NULL,          -- fixed_price | time_and_materials
    sold_hours    INT NOT NULL,
    rate_per_hour NUMERIC(8,2) NOT NULL,
    started_at    DATE NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery.time_entries (
    id            SERIAL PRIMARY KEY,
    project_id    INT NOT NULL REFERENCES delivery.projects(id),
    consultant_id INT NOT NULL REFERENCES people.consultants(id),
    worked_on     DATE NOT NULL,
    hours         NUMERIC(5,2) NOT NULL,
    billable      BOOLEAN NOT NULL,
    invoiced      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS billing.invoices (
    id          SERIAL PRIMARY KEY,
    project_id  INT NOT NULL REFERENCES delivery.projects(id),
    issued_at   DATE NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    status      TEXT NOT NULL
);

-- ── dados ────────────────────────────────────────────────────────

TRUNCATE billing.invoices, delivery.time_entries, delivery.projects,
         billing.clients, people.consultants RESTART IDENTITY CASCADE;

-- 14 consultores em quatro escalões. A capacidade contratada é igual
-- para quase todos; o que difere é quanto dela chega a ser faturável.
INSERT INTO people.consultants (name, grade, cost_per_hour, weekly_capacity)
SELECT
    (ARRAY['Ana Reis','Bruno Sá','Carla Nunes','Diogo Melo','Eva Pinto','Filipe Rocha',
           'Gabriela Lima','Hugo Matos','Inês Cardoso','João Faria','Rita Bastos',
           'Miguel Antunes','Sofia Vaz','Tiago Duarte'])[g],
    (ARRAY['junior','consultant','senior','principal'])[1 + g % 4],
    (ARRAY[28, 42, 58, 85])[1 + g % 4]::NUMERIC(8,2),
    40
FROM generate_series(1, 14) g;

INSERT INTO billing.clients (name, industry)
SELECT
    (ARRAY['Banco Atlântico','Seguros Horizonte','Retalho Ibérico','Energia Verde',
           'Farma Nova','Telecom Sul','Logística Douro','Imobiliária Praça',
           'Media Central','Indústria Tejo'])[g],
    (ARRAY['banca','seguros','retalho','energia','saúde','telecom','logística',
           'imobiliário','media','indústria'])[g]
FROM generate_series(1, 10) g;

-- 24 projectos. Os de preço fixo são onde o estouro dói — no
-- time-and-materials, mais horas é mais fatura.
INSERT INTO delivery.projects (client_id, name, contract_type, sold_hours, rate_per_hour, started_at, status)
SELECT
    1 + g % 10,
    (ARRAY['Migração','Auditoria','Implementação','Redesenho','Integração','Roadmap',
           'Suporte','Formação'])[1 + g % 8] || ' ' || (2025 + (g % 2)),
    CASE WHEN g % 3 = 0 THEN 'time_and_materials' ELSE 'fixed_price' END,
    120 + (g * 37) % 380,
    (65 + (g * 11) % 60)::NUMERIC(8,2),
    (CURRENT_DATE - INTERVAL '14 months' + (g * 17) * INTERVAL '1 day')::DATE,
    CASE WHEN g % 7 = 0 THEN 'closed' ELSE 'active' END
FROM generate_series(1, 24) g;

-- Registos de tempo ao longo de 12 meses.
--
-- Três coisas plantadas de propósito:
--   • ~22% das horas não são faturáveis (interno, pré-venda, formação);
--   • quatro projectos de preço fixo passam as horas vendidas;
--   • um bolso de horas faturáveis fica por faturar — o trabalho está
--     feito, o dinheiro não entrou.
INSERT INTO delivery.time_entries (project_id, consultant_id, worked_on, hours, billable, invoiced)
SELECT
    p.id,
    1 + (g * 5 + p.id) % 14,
    (CURRENT_DATE - INTERVAL '12 months' + ((g * 3 + p.id * 7) % 360) * INTERVAL '1 day')::DATE,
    (2 + (g + p.id) % 7)::NUMERIC(5,2),
    -- ~27% não faturável: interno, pré-venda, formação. Uma consultora
    -- que reporte 90% faturável ou está a mentir ou não está a contar
    -- as horas todas — e ninguém acredita no número.
    ((g + p.id) % 11) > 2,
    CASE
        WHEN ((g + p.id) % 11) <= 2 THEN FALSE     -- não faturável nunca é faturado
        WHEN p.id % 6 = 0 THEN FALSE               -- projectos com trabalho por faturar
        ELSE TRUE
    END
FROM delivery.projects p
-- Um terço dos projectos consome muito mais horas do que as vendidas.
-- É onde o preço fixo dói, e é a razão de a pergunta existir.
CROSS JOIN LATERAL generate_series(1, CASE WHEN p.id % 3 = 1 THEN 62 ELSE 26 END) g;

INSERT INTO billing.invoices (project_id, issued_at, amount, status)
SELECT
    p.id,
    (CURRENT_DATE - INTERVAL '11 months' + (g * 29 + p.id * 11) % 330 * INTERVAL '1 day')::DATE,
    (p.rate_per_hour * (20 + (g * 13 + p.id) % 60))::NUMERIC(12,2),
    CASE WHEN (g + p.id) % 13 = 0 THEN 'overdue' ELSE 'paid' END
FROM delivery.projects p
CROSS JOIN generate_series(1, 3) g;

CREATE INDEX IF NOT EXISTS idx_te_project ON delivery.time_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_te_consultant ON delivery.time_entries(consultant_id);
CREATE INDEX IF NOT EXISTS idx_te_worked ON delivery.time_entries(worked_on);
CREATE INDEX IF NOT EXISTS idx_inv_project ON billing.invoices(project_id);

COMMIT;
