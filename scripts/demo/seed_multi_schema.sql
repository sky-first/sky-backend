-- ─────────────────────────────────────────────────────────────────────
-- Public demo — multi-schema synthetic dataset (Cenário B)
-- ─────────────────────────────────────────────────────────────────────
--
-- 5 schemas mapping to 5 separate Connection records in the app:
--   crm            → Sales source-of-truth
--   marketing      → Marketing source-of-truth
--   finance        → Revenue / costs derived from Sales
--   web_analytics  → Site sessions / conversions
--   product_usage  → Customer adoption + health
--
-- Data is cross-referenced so cross-department queries work end-to-end:
--   marketing.campaigns → marketing.leads → crm.contacts → crm.opportunities → crm.deals → finance.invoices
--   crm.accounts       ↔ product_usage.accounts_health
--   web_analytics.sessions.campaign → marketing.campaigns.name
--
-- Idempotent: TRUNCATE before INSERT so a nightly cron can wipe
-- vandalism without dropping the schemas.
--
-- Provision:
--   PGPASSWORD=$PG_PASS psql -h sky-demo-pg.postgres.database.azure.com \
--     -U demoadmin -d demo_dataset -f scripts/demo/seed_multi_schema.sql
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

-- ─── Schemas ─────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS marketing;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS web_analytics;
CREATE SCHEMA IF NOT EXISTS product_usage;

-- ─── Read-only role for the app to use ──────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo_reader') THEN
        CREATE ROLE demo_reader LOGIN PASSWORD 'rotate-me-after-seed';
    END IF;
END $$;

-- ─── crm.* ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.sales_reps (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    region TEXT NOT NULL,
    quota NUMERIC(12,2) NOT NULL,
    hired_on DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.accounts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT UNIQUE NOT NULL,
    industry TEXT NOT NULL,
    country TEXT NOT NULL,
    employees INT NOT NULL,
    plan TEXT NOT NULL CHECK (plan IN ('starter','pro','business','enterprise')),
    signup_date DATE NOT NULL,
    arr NUMERIC(12,2) NOT NULL,
    owner_rep_id INT REFERENCES crm.sales_reps(id)
);

CREATE TABLE IF NOT EXISTS crm.contacts (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.opportunities (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    contact_id INT REFERENCES crm.contacts(id),
    owner_rep_id INT REFERENCES crm.sales_reps(id),
    name TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('discovery','demo','proposal','negotiation','closed_won','closed_lost')),
    expected_close_date DATE,
    actual_close_date DATE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.deals (
    id SERIAL PRIMARY KEY,
    opportunity_id INT NOT NULL REFERENCES crm.opportunities(id) ON DELETE CASCADE,
    amount NUMERIC(12,2) NOT NULL,
    closed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (opportunity_id)
);

CREATE TABLE IF NOT EXISTS crm.activities (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('call','email','meeting','demo','note')),
    occurred_at TIMESTAMPTZ NOT NULL,
    rep_id INT REFERENCES crm.sales_reps(id)
);

-- ─── marketing.* ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS marketing.channels (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('paid','organic','referral','content','outbound','events')),
    is_paid BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS marketing.campaigns (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    channel_id INT NOT NULL REFERENCES marketing.channels(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    budget NUMERIC(10,2) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned','active','paused','completed','cancelled'))
);

CREATE TABLE IF NOT EXISTS marketing.leads (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT,
    source_campaign_id INT REFERENCES marketing.campaigns(id),
    score INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('new','working','mql','sql','converted','lost')),
    created_at TIMESTAMPTZ NOT NULL,
    converted_account_id INT REFERENCES crm.accounts(id),
    converted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS marketing.mqls (
    id SERIAL PRIMARY KEY,
    lead_id INT NOT NULL REFERENCES marketing.leads(id) ON DELETE CASCADE,
    qualified_at TIMESTAMPTZ NOT NULL,
    score_at_qualification INT NOT NULL,
    rep_id INT REFERENCES crm.sales_reps(id)
);

CREATE TABLE IF NOT EXISTS marketing.ad_spend (
    id SERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES marketing.campaigns(id) ON DELETE CASCADE,
    spend_date DATE NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    impressions INT NOT NULL,
    clicks INT NOT NULL
);

CREATE TABLE IF NOT EXISTS marketing.email_events (
    id SERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES marketing.campaigns(id) ON DELETE CASCADE,
    recipient_email TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('sent','delivered','opened','clicked','bounced','unsubscribed')),
    event_at TIMESTAMPTZ NOT NULL
);

-- ─── finance.* ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finance.subscriptions (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    mrr NUMERIC(10,2) NOT NULL,
    started_at DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','paused','cancelled','trialing')),
    cancelled_at DATE,
    UNIQUE (account_id)
);

CREATE TABLE IF NOT EXISTS finance.invoices (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    deal_id INT REFERENCES crm.deals(id),
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    issued_at DATE NOT NULL,
    paid_at DATE,
    status TEXT NOT NULL CHECK (status IN ('draft','open','paid','overdue','void'))
);

CREATE TABLE IF NOT EXISTS finance.mrr_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    total_mrr NUMERIC(12,2) NOT NULL,
    new_mrr NUMERIC(12,2) NOT NULL,
    expansion_mrr NUMERIC(12,2) NOT NULL,
    contraction_mrr NUMERIC(12,2) NOT NULL,
    churn_mrr NUMERIC(12,2) NOT NULL,
    customers_active INT NOT NULL,
    customers_new INT NOT NULL,
    customers_churned INT NOT NULL
);

CREATE TABLE IF NOT EXISTS finance.costs (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('payroll','infrastructure','marketing','sales','tools','office','travel','legal')),
    vendor TEXT NOT NULL,
    incurred_on DATE NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    department TEXT
);

-- ─── web_analytics.* ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS web_analytics.utm_sources (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    medium TEXT NOT NULL,
    campaign_name TEXT,
    UNIQUE (source, medium, campaign_name)
);

CREATE TABLE IF NOT EXISTS web_analytics.sessions (
    id SERIAL PRIMARY KEY,
    visitor_uuid UUID NOT NULL,
    utm_source_id INT REFERENCES web_analytics.utm_sources(id),
    landing_page TEXT NOT NULL,
    referrer TEXT,
    country TEXT NOT NULL,
    device_type TEXT NOT NULL CHECK (device_type IN ('desktop','mobile','tablet')),
    started_at TIMESTAMPTZ NOT NULL,
    duration_seconds INT NOT NULL,
    converted BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS web_analytics.conversions (
    id SERIAL PRIMARY KEY,
    session_id INT NOT NULL REFERENCES web_analytics.sessions(id) ON DELETE CASCADE,
    goal TEXT NOT NULL CHECK (goal IN ('signup','demo_request','contact','newsletter','download','trial')),
    value NUMERIC(10,2) NOT NULL DEFAULT 0,
    converted_at TIMESTAMPTZ NOT NULL,
    converted_to_lead_id INT REFERENCES marketing.leads(id)
);

-- ─── product_usage.* ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_usage.events (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    feature TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS product_usage.feature_adoption (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    feature_name TEXT NOT NULL,
    first_used_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL,
    usage_count INT NOT NULL,
    UNIQUE (account_id, feature_name)
);

CREATE TABLE IF NOT EXISTS product_usage.accounts_health (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES crm.accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    health_score INT NOT NULL CHECK (health_score BETWEEN 0 AND 100),
    churn_risk TEXT NOT NULL CHECK (churn_risk IN ('low','medium','high','critical')),
    last_login_at TIMESTAMPTZ,
    dau_30d INT NOT NULL DEFAULT 0,
    UNIQUE (account_id, snapshot_date)
);

-- ─── Indices for query performance ──────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_crm_opps_account    ON crm.opportunities(account_id);
CREATE INDEX IF NOT EXISTS idx_crm_opps_stage      ON crm.opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_crm_opps_close      ON crm.opportunities(actual_close_date);
CREATE INDEX IF NOT EXISTS idx_crm_deals_closed    ON crm.deals(closed_at);
CREATE INDEX IF NOT EXISTS idx_crm_acts_acc_date   ON crm.activities(account_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_mkt_leads_camp      ON marketing.leads(source_campaign_id);
CREATE INDEX IF NOT EXISTS idx_mkt_leads_status    ON marketing.leads(status);
CREATE INDEX IF NOT EXISTS idx_mkt_spend_camp_date ON marketing.ad_spend(campaign_id, spend_date);
CREATE INDEX IF NOT EXISTS idx_fin_inv_acc_issued  ON finance.invoices(account_id, issued_at);
CREATE INDEX IF NOT EXISTS idx_web_sess_started    ON web_analytics.sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_pu_events_acc       ON product_usage.events(account_id, occurred_at);

-- ─── Reset for re-runs ──────────────────────────────────────────────
TRUNCATE
    crm.activities, crm.deals, crm.opportunities, crm.contacts, crm.accounts, crm.sales_reps,
    marketing.email_events, marketing.ad_spend, marketing.mqls, marketing.leads, marketing.campaigns, marketing.channels,
    finance.costs, finance.mrr_snapshots, finance.invoices, finance.subscriptions,
    web_analytics.conversions, web_analytics.sessions, web_analytics.utm_sources,
    product_usage.accounts_health, product_usage.feature_adoption, product_usage.events
RESTART IDENTITY CASCADE;

COMMIT;

-- The seed data inserts live in seed_multi_schema_data.sql so the
-- DDL above can be replayed independently when we add columns later.
