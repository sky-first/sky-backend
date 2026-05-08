-- ─────────────────────────────────────────────────────────────────
-- Public-demo synthetic dataset — multi-schema (Cenário B)
-- ─────────────────────────────────────────────────────────────────
-- Five departments, five Postgres schemas, ~5k rows total. Designed
-- so the AI agent can answer cross-departmental prospect questions
-- like "which marketing campaigns sourced the highest-MRR accounts?"
-- without needing real customer data.
--
-- Each demo Space gets one or more SpaceConnections pointing here
-- read-only via the demo_reader role.
--
-- Provision (run as the demoadmin / server admin):
--   psql "$DEMO_DB_URL" -f scripts/demo/seed_multi_schema.sql
--
-- Re-run safely: every CREATE is IF NOT EXISTS and the data section
-- TRUNCATE…RESTART IDENTITY CASCADE before INSERT, so the cleanup
-- cron can call it nightly to wipe vandalism without dropping
-- schemas.
--
-- Cross-schema FKs intentionally:
--   marketing.leads.converted_to_opportunity_id → crm.opportunities
--   marketing.leads.contact_id                  → crm.contacts
--   finance.subscriptions.account_id            → crm.accounts
--   product_usage.feature_adoption.account_id   → crm.accounts
--   product_usage.account_health.account_id     → crm.accounts (1:1)
--   web_analytics.sessions.account_id           → crm.accounts (nullable; anon visitors)
-- ─────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS marketing;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS web_analytics;
CREATE SCHEMA IF NOT EXISTS product_usage;

-- ── crm ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.accounts (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    industry     TEXT NOT NULL,
    plan         TEXT NOT NULL CHECK (plan IN ('starter','pro','enterprise')),
    region       TEXT NOT NULL,
    signup_date  DATE NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS crm.contacts (
    id          SERIAL PRIMARY KEY,
    account_id  INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    role_title  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm.opportunities (
    id           SERIAL PRIMARY KEY,
    account_id   INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    stage        TEXT NOT NULL CHECK (stage IN ('prospect','qualified','negotiation','closed_won','closed_lost')),
    amount       NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    close_date   DATE NOT NULL,
    owner_email  TEXT NOT NULL
);

-- ── marketing ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS marketing.campaigns (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('email','social','search','display','event')),
    started_at  DATE NOT NULL,
    ended_at    DATE NOT NULL,
    budget      NUMERIC(10,2) NOT NULL,
    spend       NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS marketing.leads (
    id           SERIAL PRIMARY KEY,
    campaign_id  INT REFERENCES marketing.campaigns(id) ON DELETE SET NULL,
    contact_id   INT REFERENCES crm.contacts(id) ON DELETE SET NULL,
    email        TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('organic','paid','referral','direct','partner')),
    score        INT NOT NULL CHECK (score BETWEEN 0 AND 100),
    converted_to_opportunity_id INT REFERENCES crm.opportunities(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketing.email_events (
    id           SERIAL PRIMARY KEY,
    campaign_id  INT NOT NULL REFERENCES marketing.campaigns(id) ON DELETE CASCADE,
    lead_id      INT REFERENCES marketing.leads(id) ON DELETE CASCADE,
    event_type   TEXT NOT NULL CHECK (event_type IN ('sent','open','click','bounce','unsubscribe')),
    occurred_at  TIMESTAMPTZ NOT NULL
);

-- ── finance ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finance.subscriptions (
    id              SERIAL PRIMARY KEY,
    account_id      INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    plan            TEXT NOT NULL CHECK (plan IN ('starter','pro','enterprise')),
    monthly_amount  NUMERIC(10,2) NOT NULL,
    started_at      DATE NOT NULL,
    cancelled_at    DATE
);

CREATE TABLE IF NOT EXISTS finance.invoices (
    id               SERIAL PRIMARY KEY,
    subscription_id  INT NOT NULL REFERENCES finance.subscriptions(id) ON DELETE CASCADE,
    issued_at        DATE NOT NULL,
    amount           NUMERIC(10,2) NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('draft','sent','paid','overdue','void'))
);

-- ── web_analytics ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS web_analytics.sessions (
    id            SERIAL PRIMARY KEY,
    account_id    INT REFERENCES crm.accounts(id) ON DELETE SET NULL,  -- nullable: anon visitors
    visitor_uuid  UUID NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL,
    ended_at      TIMESTAMPTZ NOT NULL,
    referrer      TEXT,
    utm_source    TEXT,
    utm_campaign  TEXT,
    pages_viewed  INT NOT NULL CHECK (pages_viewed >= 0)
);

CREATE TABLE IF NOT EXISTS web_analytics.events (
    id           SERIAL PRIMARY KEY,
    session_id   INT NOT NULL REFERENCES web_analytics.sessions(id) ON DELETE CASCADE,
    event_name   TEXT NOT NULL,
    page_path    TEXT NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL
);

-- ── product_usage ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_usage.feature_adoption (
    id              SERIAL PRIMARY KEY,
    account_id      INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    feature_name    TEXT NOT NULL,
    first_used_at   DATE NOT NULL,
    times_used_30d  INT NOT NULL CHECK (times_used_30d >= 0)
);

CREATE TABLE IF NOT EXISTS product_usage.account_health (
    id              SERIAL PRIMARY KEY,
    account_id      INT UNIQUE NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    score           INT NOT NULL CHECK (score BETWEEN 0 AND 100),
    risk_level      TEXT NOT NULL CHECK (risk_level IN ('healthy','watch','risk','churn')),
    last_login_at   TIMESTAMPTZ,
    seats_used      INT NOT NULL DEFAULT 0,
    seats_paid      INT NOT NULL DEFAULT 0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_crm_contacts_account_id    ON crm.contacts(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_opps_account_id        ON crm.opportunities(account_id);
CREATE INDEX IF NOT EXISTS idx_mkt_leads_campaign_id      ON marketing.leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_mkt_leads_contact_id       ON marketing.leads(contact_id);
CREATE INDEX IF NOT EXISTS idx_fin_subs_account_id        ON finance.subscriptions(account_id);
CREATE INDEX IF NOT EXISTS idx_fin_inv_subscription_id    ON finance.invoices(subscription_id);
CREATE INDEX IF NOT EXISTS idx_wa_sessions_account_id     ON web_analytics.sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_wa_events_session_id       ON web_analytics.events(session_id);
CREATE INDEX IF NOT EXISTS idx_pu_features_account_id     ON product_usage.feature_adoption(account_id);

-- ── DATA ─────────────────────────────────────────────────────────
TRUNCATE
    crm.accounts, crm.contacts, crm.opportunities,
    marketing.campaigns, marketing.leads, marketing.email_events,
    finance.subscriptions, finance.invoices,
    web_analytics.sessions, web_analytics.events,
    product_usage.feature_adoption, product_usage.account_health
RESTART IDENTITY CASCADE;

-- 50 accounts
INSERT INTO crm.accounts (name, industry, plan, region, signup_date, is_active)
SELECT
    (ARRAY['Acme','Globex','Initech','Umbrella','Soylent','Tyrell','Wonka','Stark','Wayne','Hooli',
           'Pied Piper','Massive Dynamic','Cyberdyne','Oscorp','LexCorp','Vandelay','Sirius','Aperture',
           'Black Mesa','Bluth','Nakatomi','Buy More','Spacely','Yoyodyne','Gringotts','Ollivanders',
           'Krusty','Springfield','Duff','Globex','Mega City','Tessier','Pearson','Acme Labs','Cogswell',
           'Hyperion','Roxxon','Pym','Nakamoto','Crane Tech','Fortis','Apex','Helios','Lumon','Quartet',
           'Vector','Praxis','Echelon','Beacon','Atlas'])[g] || ' ' ||
    (ARRAY['Inc','Corp','Group','Labs','Industries'])[1 + g % 5],
    (ARRAY['SaaS','Retail','Finance','Healthcare','Manufacturing','Media','Education','Logistics'])[1 + g % 8],
    (ARRAY['starter','pro','enterprise'])[1 + g % 3],
    (ARRAY['US','EU','APAC','LATAM'])[1 + g % 4],
    (CURRENT_DATE - INTERVAL '24 months' + ((g * 7) % 730) * INTERVAL '1 day')::DATE,
    g % 11 <> 0  -- ~9% inactive
FROM generate_series(1, 50) g;

-- 200 contacts (4 per account)
INSERT INTO crm.contacts (account_id, first_name, last_name, email, role_title)
SELECT
    1 + ((g - 1) / 4),
    (ARRAY['Alice','Bob','Carlos','Diana','Erik','Fiona','George','Helena','Iris','Jack',
           'Kira','Luis','Maria','Noah','Olivia','Pablo','Quinn','Rita','Sam','Tara'])[1 + g % 20],
    'Doe' || g,
    'contact' || g || '@example.com',
    (ARRAY['CEO','CTO','VP Sales','Director','Manager','Engineer','Analyst','PM'])[1 + g % 8]
FROM generate_series(1, 200) g;

-- 100 opportunities — close_date spans last 18 months so current-year filters find data
INSERT INTO crm.opportunities (account_id, stage, amount, close_date, owner_email)
SELECT
    1 + (g % 50),
    (ARRAY['prospect','qualified','negotiation','closed_won','closed_lost'])[1 + g % 5],
    (5000 + (g * 137) % 95000)::NUMERIC(12,2),
    (CURRENT_DATE - INTERVAL '18 months' + ((g * 5) % 550) * INTERVAL '1 day')::DATE,
    'rep' || (1 + g % 8) || '@skyfirstlabs.com'
FROM generate_series(1, 100) g;

-- 10 campaigns
INSERT INTO marketing.campaigns (name, channel, started_at, ended_at, budget, spend)
SELECT
    'Campaign ' || (ARRAY['Q1 Awareness','Q2 Demand Gen','Q3 ABM','Q4 Renewal','Spring Promo',
                          'Webinar Series','Conference Push','Partner Co-Marketing','Retargeting',
                          'Brand Refresh'])[g],
    (ARRAY['email','social','search','display','event'])[1 + g % 5],
    DATE '2025-01-01' + (g * 30)::INT,
    DATE '2025-01-01' + (g * 30 + 30)::INT,
    (10000 + g * 5000)::NUMERIC(10,2),
    (8000 + g * 4000)::NUMERIC(10,2)
FROM generate_series(1, 10) g;

-- 200 leads (linked to campaigns + ~half to contacts)
INSERT INTO marketing.leads (campaign_id, contact_id, email, source, score, converted_to_opportunity_id, created_at)
SELECT
    1 + (g % 10),
    CASE WHEN g % 2 = 0 THEN 1 + (g % 200) ELSE NULL END,
    'lead' || g || '@example.com',
    (ARRAY['organic','paid','referral','direct','partner'])[1 + g % 5],
    10 + (g * 7) % 90,
    -- ~25% of leads converted to an opportunity
    CASE WHEN g % 4 = 0 THEN 1 + (g % 100) ELSE NULL END,
    NOW() - (g * INTERVAL '1 day')
FROM generate_series(1, 200) g;

-- 500 email events
INSERT INTO marketing.email_events (campaign_id, lead_id, event_type, occurred_at)
SELECT
    1 + (g % 10),
    1 + (g % 200),
    (ARRAY['sent','open','click','bounce','unsubscribe'])[1 + g % 5],
    NOW() - (g * INTERVAL '1 hour')
FROM generate_series(1, 500) g;

-- 50 subscriptions (one per account, mirror plan)
-- started_at anchored to recent dates so MRR / cancellation queries find data
INSERT INTO finance.subscriptions (account_id, plan, monthly_amount, started_at, cancelled_at)
SELECT
    a.id,
    a.plan,
    CASE a.plan
        WHEN 'starter' THEN 49.00
        WHEN 'pro' THEN 199.00
        WHEN 'enterprise' THEN 999.00
    END,
    (CURRENT_DATE - INTERVAL '24 months' + ((a.id * 7) % 365) * INTERVAL '1 day')::DATE,
    CASE WHEN a.is_active THEN NULL
         ELSE (CURRENT_DATE - INTERVAL '24 months' + ((a.id * 7) % 365) * INTERVAL '1 day' + INTERVAL '180 days')::DATE
    END
FROM crm.accounts a;

-- 12 monthly invoices per active subscription (last 12 months)
-- issued_at uses NOW()-based offsets so "last 12 months" queries always return data
INSERT INTO finance.invoices (subscription_id, issued_at, amount, status)
SELECT
    s.id,
    DATE_TRUNC('month', NOW()) - ((12 - i) * INTERVAL '1 month'),
    s.monthly_amount,
    CASE i WHEN 12 THEN 'sent' WHEN 11 THEN 'paid' ELSE 'paid' END
FROM finance.subscriptions s
CROSS JOIN generate_series(1, 12) AS i
WHERE s.cancelled_at IS NULL;

-- 1000 sessions (mix of authenticated + anon)
INSERT INTO web_analytics.sessions (account_id, visitor_uuid, started_at, ended_at, referrer, utm_source, utm_campaign, pages_viewed)
SELECT
    CASE WHEN g % 3 = 0 THEN NULL ELSE 1 + (g % 50) END,
    gen_random_uuid(),
    NOW() - (g * INTERVAL '37 minutes'),
    NOW() - (g * INTERVAL '37 minutes') + (5 + (g % 30)) * INTERVAL '1 minute',
    (ARRAY['google.com','linkedin.com','twitter.com','direct','newsletter'])[1 + g % 5],
    (ARRAY['google','linkedin','twitter','direct','email'])[1 + g % 5],
    (ARRAY['Q1 Awareness','Q2 Demand Gen','Q3 ABM','Q4 Renewal','Spring Promo','direct'])[1 + g % 6],
    1 + (g % 12)
FROM generate_series(1, 1000) g;

-- 3000 events (~3 per session)
INSERT INTO web_analytics.events (session_id, event_name, page_path, occurred_at)
SELECT
    1 + ((g - 1) / 3),
    (ARRAY['page_view','cta_click','form_submit','download','signup','demo_request'])[1 + g % 6],
    (ARRAY['/','/pricing','/product','/blog','/demo','/login','/dashboard'])[1 + g % 7],
    NOW() - (g * INTERVAL '13 minutes')
FROM generate_series(1, 3000) g;

-- 300 feature_adoption rows (~6 features per account)
INSERT INTO product_usage.feature_adoption (account_id, feature_name, first_used_at, times_used_30d)
SELECT
    1 + ((g - 1) / 6),
    (ARRAY['ai_chat','dashboards','knowledge_graph','agents','connections','exports','sharing','alerts'])[1 + g % 8],
    DATE '2024-06-01' + ((g * 17) % 365)::INT,
    (g * 11) % 250
FROM generate_series(1, 300) g;

-- 50 account_health (1:1 with accounts)
INSERT INTO product_usage.account_health (account_id, score, risk_level, last_login_at, seats_used, seats_paid)
SELECT
    a.id,
    CASE
        WHEN a.is_active AND a.plan = 'enterprise' THEN 70 + (a.id * 3) % 30
        WHEN a.is_active AND a.plan = 'pro'        THEN 50 + (a.id * 5) % 40
        WHEN a.is_active                            THEN 30 + (a.id * 7) % 50
        ELSE                                              5 + (a.id * 11) % 20
    END,
    CASE
        WHEN NOT a.is_active                   THEN 'churn'
        WHEN a.id % 7 = 0                      THEN 'risk'
        WHEN a.id % 5 = 0                      THEN 'watch'
        ELSE                                        'healthy'
    END,
    CASE WHEN a.is_active THEN NOW() - ((a.id * 2) || ' hours')::INTERVAL ELSE NULL END,
    CASE a.plan WHEN 'starter' THEN 1 WHEN 'pro' THEN 5 ELSE 25 END,
    CASE a.plan WHEN 'starter' THEN 2 WHEN 'pro' THEN 10 ELSE 50 END
FROM crm.accounts a;

-- ── GRANTs to demo_reader (idempotent) ───────────────────────────
DO $grants$
DECLARE s TEXT;
BEGIN
    -- Create role if it doesn't exist (no password set here — admin
    -- sets it via ALTER USER demo_reader WITH PASSWORD '...' separately).
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo_reader') THEN
        CREATE ROLE demo_reader LOGIN;
    END IF;

    FOR s IN SELECT unnest(ARRAY['crm','marketing','finance','web_analytics','product_usage'])
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO demo_reader', s);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO demo_reader', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO demo_reader', s);
    END LOOP;
END $grants$;

COMMIT;
