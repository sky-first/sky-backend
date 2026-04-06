-- ============================================================
-- NovaTech Demo Data — 16 tables across 4 departments
-- B2B SaaS company, ~200 employees, ~$10M ARR
-- Data: April 2025 — March 2026 (12 months)
-- ============================================================

DROP SCHEMA IF EXISTS demo_novatech CASCADE;
CREATE SCHEMA demo_novatech;

-- ════════════════════════════════════════════════════════════
-- FINANCE DEPARTMENT
-- ════════════════════════════════════════════════════════════

-- Customers (50 rows)
CREATE TABLE demo_novatech.customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    segment VARCHAR(50),  -- enterprise, mid-market, startup
    industry VARCHAR(100),
    country VARCHAR(50),
    mrr NUMERIC(12,2),
    contract_start DATE,
    contract_end DATE,
    health_score INTEGER CHECK (health_score BETWEEN 0 AND 100)
);

INSERT INTO demo_novatech.customers (name, segment, industry, country, mrr, contract_start, contract_end, health_score) VALUES
('Acme Corp', 'enterprise', 'Technology', 'USA', 45000, '2024-01-15', '2026-01-15', 92),
('GlobalTech Solutions', 'enterprise', 'Technology', 'UK', 38000, '2024-03-01', '2026-03-01', 88),
('NorthStar Industries', 'enterprise', 'Manufacturing', 'Germany', 52000, '2023-11-01', '2025-11-01', 75),
('BluePeak Financial', 'enterprise', 'Finance', 'USA', 41000, '2024-06-01', '2026-06-01', 95),
('Horizon Healthcare', 'enterprise', 'Healthcare', 'Canada', 36000, '2024-02-15', '2026-02-15', 82),
('Quantum Analytics', 'mid-market', 'Analytics', 'USA', 18000, '2024-07-01', '2026-07-01', 90),
('Swift Logistics', 'mid-market', 'Logistics', 'Netherlands', 15000, '2024-04-01', '2026-04-01', 78),
('ClearView Media', 'mid-market', 'Media', 'USA', 12000, '2024-08-01', '2026-08-01', 85),
('DataBridge Systems', 'mid-market', 'Technology', 'Australia', 22000, '2024-01-01', '2026-01-01', 70),
('EcoTech Green', 'mid-market', 'Energy', 'Sweden', 16000, '2024-05-15', '2026-05-15', 88),
('RedLine Retail', 'mid-market', 'Retail', 'UK', 14000, '2024-09-01', '2026-09-01', 65),
('Summit Education', 'mid-market', 'Education', 'USA', 11000, '2024-03-15', '2026-03-15', 92),
('Atlas Pharma', 'enterprise', 'Pharma', 'Switzerland', 48000, '2023-09-01', '2025-09-01', 80),
('CyberShield Security', 'mid-market', 'Security', 'Israel', 20000, '2024-11-01', '2026-11-01', 94),
('FreshWave Foods', 'mid-market', 'Food & Beverage', 'Brazil', 9000, '2024-06-15', '2026-06-15', 72),
('IronForge Manufacturing', 'enterprise', 'Manufacturing', 'Japan', 35000, '2024-01-01', '2026-01-01', 68),
('LightPath Telecom', 'enterprise', 'Telecom', 'India', 30000, '2024-04-01', '2026-04-01', 85),
('NextGen Robotics', 'startup', 'Robotics', 'USA', 5000, '2025-01-01', '2026-01-01', 95),
('OceanView Travel', 'startup', 'Travel', 'Spain', 4500, '2025-02-01', '2026-02-01', 80),
('PrimeHealth Clinics', 'mid-market', 'Healthcare', 'USA', 13000, '2024-10-01', '2026-10-01', 87),
('QuickServe Delivery', 'startup', 'Logistics', 'UK', 6000, '2025-03-01', '2026-03-01', 90),
('RiverBank Capital', 'enterprise', 'Finance', 'USA', 55000, '2023-06-01', '2025-06-01', 60),
('SilverLine Airlines', 'enterprise', 'Aviation', 'UAE', 42000, '2024-07-01', '2026-07-01', 78),
('TrueNorth Consulting', 'mid-market', 'Consulting', 'Canada', 17000, '2024-08-15', '2026-08-15', 91),
('UrbanGrow AgriTech', 'startup', 'Agriculture', 'Netherlands', 7000, '2025-01-15', '2026-01-15', 85),
('Vertex Energy', 'mid-market', 'Energy', 'Norway', 19000, '2024-05-01', '2026-05-01', 76),
('WavePoint Media', 'startup', 'Media', 'USA', 3500, '2025-03-01', '2026-03-01', 88),
('XcelPay Payments', 'mid-market', 'Fintech', 'Singapore', 21000, '2024-09-01', '2026-09-01', 93),
('YieldMax Investments', 'enterprise', 'Finance', 'UK', 47000, '2024-02-01', '2026-02-01', 82),
('ZenithCloud Services', 'mid-market', 'Cloud', 'USA', 16500, '2024-11-15', '2026-11-15', 89),
('AlphaStrike Gaming', 'startup', 'Gaming', 'South Korea', 8000, '2025-02-15', '2026-02-15', 96),
('BrightPath Learning', 'mid-market', 'EdTech', 'USA', 12500, '2024-06-01', '2026-06-01', 84),
('CoreStack Infra', 'mid-market', 'Infrastructure', 'Germany', 23000, '2024-03-01', '2026-03-01', 77),
('DeltaForce Defense', 'enterprise', 'Defense', 'USA', 60000, '2023-08-01', '2025-08-01', 70),
('EliteServices Group', 'mid-market', 'Professional Services', 'UK', 14500, '2024-10-15', '2026-10-15', 86),
('FluxData Analytics', 'startup', 'Data', 'USA', 5500, '2025-01-01', '2026-01-01', 92),
('GreenLeaf Organics', 'startup', 'Organic Food', 'France', 4000, '2025-02-01', '2026-02-01', 79),
('HyperLoop Transport', 'mid-market', 'Transport', 'USA', 18500, '2024-07-15', '2026-07-15', 81),
('InnoTech Labs', 'startup', 'R&D', 'Israel', 6500, '2025-03-15', '2026-03-15', 94),
('JetStream Logistics', 'mid-market', 'Logistics', 'Australia', 11500, '2024-08-01', '2026-08-01', 73),
('KnightBridge Capital', 'enterprise', 'Private Equity', 'UK', 50000, '2024-01-15', '2026-01-15', 88),
('LaunchPad Ventures', 'startup', 'VC', 'USA', 3000, '2025-04-01', '2026-04-01', 97),
('MegaByte Storage', 'mid-market', 'Storage', 'Japan', 15500, '2024-09-15', '2026-09-15', 80),
('NovaEnergy Solar', 'mid-market', 'Solar Energy', 'Germany', 20500, '2024-04-15', '2026-04-15', 87),
('OptimalRoute Fleet', 'mid-market', 'Fleet Management', 'Canada', 13500, '2024-11-01', '2026-11-01', 75),
('PeakPerformance Sports', 'startup', 'Sports Tech', 'USA', 4800, '2025-01-15', '2026-01-15', 91),
('QuantumLeap AI', 'mid-market', 'AI/ML', 'USA', 25000, '2024-05-01', '2026-05-01', 95),
('RapidScale Cloud', 'mid-market', 'Cloud', 'Ireland', 19500, '2024-06-15', '2026-06-15', 83),
('SmartGrid Solutions', 'enterprise', 'Utilities', 'USA', 44000, '2024-02-15', '2026-02-15', 79),
('TechVault Security', 'mid-market', 'Cybersecurity', 'USA', 17500, '2024-12-01', '2026-12-01', 90);

-- Revenue Monthly (24 months, growing ~8% MoM with Q4 dip)
CREATE TABLE demo_novatech.revenue_monthly (
    id SERIAL PRIMARY KEY,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    revenue NUMERIC(12,2),
    costs NUMERIC(12,2),
    net_profit NUMERIC(12,2),
    department VARCHAR(50),
    revenue_type VARCHAR(50)  -- subscription, services, expansion
);

INSERT INTO demo_novatech.revenue_monthly (month, year, revenue, costs, net_profit, department, revenue_type) VALUES
(4, 2025, 680000, 420000, 260000, 'Finance', 'subscription'),
(5, 2025, 715000, 430000, 285000, 'Finance', 'subscription'),
(6, 2025, 748000, 445000, 303000, 'Finance', 'subscription'),
(7, 2025, 790000, 460000, 330000, 'Finance', 'subscription'),
(8, 2025, 825000, 470000, 355000, 'Finance', 'subscription'),
(9, 2025, 860000, 485000, 375000, 'Finance', 'subscription'),
(10, 2025, 810000, 490000, 320000, 'Finance', 'subscription'),
(11, 2025, 780000, 495000, 285000, 'Finance', 'subscription'),
(12, 2025, 750000, 500000, 250000, 'Finance', 'subscription'),
(1, 2026, 830000, 510000, 320000, 'Finance', 'subscription'),
(2, 2026, 890000, 520000, 370000, 'Finance', 'subscription'),
(3, 2026, 950000, 530000, 420000, 'Finance', 'subscription'),
(4, 2025, 120000, 80000, 40000, 'Finance', 'services'),
(5, 2025, 135000, 85000, 50000, 'Finance', 'services'),
(6, 2025, 110000, 78000, 32000, 'Finance', 'services'),
(7, 2025, 145000, 90000, 55000, 'Finance', 'services'),
(8, 2025, 130000, 82000, 48000, 'Finance', 'services'),
(9, 2025, 155000, 95000, 60000, 'Finance', 'services'),
(10, 2025, 125000, 88000, 37000, 'Finance', 'services'),
(11, 2025, 140000, 92000, 48000, 'Finance', 'services'),
(12, 2025, 100000, 75000, 25000, 'Finance', 'services'),
(1, 2026, 160000, 98000, 62000, 'Finance', 'services'),
(2, 2026, 175000, 105000, 70000, 'Finance', 'services'),
(3, 2026, 190000, 110000, 80000, 'Finance', 'services');

-- Invoices (200 rows)
CREATE TABLE demo_novatech.invoices (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES demo_novatech.customers(id),
    amount NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20),  -- paid, pending, overdue, cancelled
    issued_date DATE NOT NULL,
    due_date DATE,
    paid_date DATE,
    department VARCHAR(50) DEFAULT 'Finance'
);

INSERT INTO demo_novatech.invoices (customer_id, amount, currency, status, issued_date, due_date, paid_date)
SELECT
    (random() * 49 + 1)::int,
    (random() * 50000 + 5000)::numeric(12,2),
    CASE WHEN random() > 0.7 THEN 'EUR' WHEN random() > 0.5 THEN 'GBP' ELSE 'USD' END,
    CASE
        WHEN random() < 0.65 THEN 'paid'
        WHEN random() < 0.85 THEN 'pending'
        WHEN random() < 0.95 THEN 'overdue'
        ELSE 'cancelled'
    END,
    ('2025-04-01'::date + (random() * 365)::int),
    ('2025-04-01'::date + (random() * 365)::int + 30),
    CASE WHEN random() < 0.65 THEN ('2025-04-01'::date + (random() * 365)::int + (random() * 25)::int) ELSE NULL END
FROM generate_series(1, 200);

-- Payments (300 rows)
CREATE TABLE demo_novatech.payments (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES demo_novatech.invoices(id),
    amount NUMERIC(12,2) NOT NULL,
    payment_date DATE NOT NULL,
    method VARCHAR(50),  -- wire, credit_card, ach, check
    reference VARCHAR(100)
);

INSERT INTO demo_novatech.payments (invoice_id, amount, payment_date, method, reference)
SELECT
    (random() * 199 + 1)::int,
    (random() * 50000 + 1000)::numeric(12,2),
    ('2025-04-01'::date + (random() * 365)::int),
    CASE
        WHEN random() < 0.4 THEN 'wire'
        WHEN random() < 0.7 THEN 'credit_card'
        WHEN random() < 0.9 THEN 'ach'
        ELSE 'check'
    END,
    'PAY-' || lpad((random() * 999999)::int::text, 6, '0')
FROM generate_series(1, 300);

-- ════════════════════════════════════════════════════════════
-- MARKETING DEPARTMENT
-- ════════════════════════════════════════════════════════════

-- Campaigns (30 rows)
CREATE TABLE demo_novatech.campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    channel VARCHAR(50),  -- google_ads, linkedin, facebook, email, content, events
    status VARCHAR(20),  -- active, paused, completed, draft
    budget NUMERIC(10,2),
    spend NUMERIC(10,2),
    impressions INTEGER,
    clicks INTEGER,
    conversions INTEGER,
    start_date DATE,
    end_date DATE
);

INSERT INTO demo_novatech.campaigns (name, channel, status, budget, spend, impressions, clicks, conversions, start_date, end_date) VALUES
('Enterprise Q2 Push', 'linkedin', 'active', 50000, 32000, 450000, 8500, 120, '2026-04-01', '2026-06-30'),
('Product Launch v3.0', 'google_ads', 'completed', 80000, 78500, 1200000, 24000, 340, '2025-10-01', '2025-12-31'),
('Developer Conference Sponsorship', 'events', 'completed', 120000, 115000, 50000, 3200, 85, '2025-09-15', '2025-09-18'),
('Content Marketing Program', 'content', 'active', 30000, 18000, 280000, 12000, 200, '2026-01-01', '2026-06-30'),
('Email Nurture Sequence', 'email', 'active', 5000, 2800, 95000, 14200, 280, '2026-02-01', '2026-05-31'),
('Facebook Brand Awareness', 'facebook', 'paused', 25000, 22000, 800000, 9600, 45, '2025-11-01', '2026-02-28'),
('Google Search - Enterprise', 'google_ads', 'active', 40000, 28000, 380000, 7600, 95, '2026-01-15', '2026-06-30'),
('LinkedIn Thought Leadership', 'linkedin', 'active', 15000, 8500, 120000, 4800, 65, '2026-03-01', '2026-06-30'),
('Webinar Series: Data Analytics', 'events', 'completed', 10000, 9200, 8500, 2100, 180, '2025-07-01', '2025-12-31'),
('Holiday Promo Campaign', 'email', 'completed', 8000, 7500, 120000, 18000, 420, '2025-11-15', '2025-12-31'),
('SEO Content Sprint', 'content', 'active', 20000, 12000, 450000, 22000, 310, '2026-01-01', '2026-03-31'),
('Partner Co-Marketing', 'events', 'active', 35000, 15000, 60000, 3500, 70, '2026-02-15', '2026-05-31'),
('Retargeting Campaign', 'google_ads', 'active', 18000, 14000, 600000, 12000, 180, '2026-01-01', '2026-04-30'),
('ABM Enterprise Accounts', 'linkedin', 'active', 60000, 25000, 85000, 2800, 42, '2026-03-01', '2026-08-31'),
('Product Demo Videos', 'content', 'completed', 25000, 24000, 180000, 9000, 150, '2025-08-01', '2025-12-31'),
('Twitter/X Community Building', 'content', 'paused', 5000, 4200, 250000, 3800, 25, '2025-10-01', '2026-03-31'),
('Startup Accelerator Sponsorship', 'events', 'completed', 15000, 15000, 12000, 800, 35, '2025-11-01', '2025-11-15'),
('Influencer Partnership', 'content', 'active', 20000, 8000, 350000, 7000, 90, '2026-02-01', '2026-07-31'),
('Black Friday SaaS Deals', 'email', 'completed', 3000, 2800, 80000, 12000, 520, '2025-11-25', '2025-11-30'),
('New Year Bundle Offer', 'email', 'completed', 4000, 3500, 70000, 10500, 380, '2025-12-26', '2026-01-05'),
('Industry Report Launch', 'content', 'active', 15000, 6000, 95000, 8500, 120, '2026-03-15', '2026-04-30'),
('LinkedIn Video Ads', 'linkedin', 'draft', 30000, 0, 0, 0, 0, '2026-05-01', '2026-07-31'),
('Google Display Network', 'google_ads', 'active', 22000, 18000, 900000, 5400, 65, '2026-01-01', '2026-06-30'),
('Customer Referral Program', 'email', 'active', 10000, 4500, 25000, 6000, 95, '2026-01-15', '2026-12-31'),
('Podcast Sponsorships', 'content', 'active', 18000, 9000, 150000, 4500, 55, '2026-02-01', '2026-06-30'),
('Trade Show: SaaStr Annual', 'events', 'draft', 75000, 0, 0, 0, 0, '2026-09-01', '2026-09-03'),
('Mid-Market Outreach', 'linkedin', 'active', 25000, 12000, 200000, 6000, 80, '2026-03-01', '2026-06-30'),
('Case Study Distribution', 'content', 'active', 8000, 3500, 45000, 5500, 75, '2026-03-15', '2026-06-30'),
('PPC Brand Protection', 'google_ads', 'active', 5000, 4200, 120000, 3600, 40, '2026-01-01', '2026-12-31'),
('Q1 Lead Gen Blitz', 'google_ads', 'completed', 45000, 44000, 650000, 15000, 210, '2026-01-01', '2026-03-31');

-- Leads (500 rows)
CREATE TABLE demo_novatech.leads (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    email VARCHAR(200),
    source VARCHAR(50),  -- organic, paid, referral, event, content
    campaign_id INTEGER REFERENCES demo_novatech.campaigns(id),
    status VARCHAR(20),  -- new, qualified, contacted, converted, lost
    score INTEGER CHECK (score BETWEEN 0 AND 100),
    created_date DATE,
    converted_date DATE
);

INSERT INTO demo_novatech.leads (name, email, source, campaign_id, status, score, created_date, converted_date)
SELECT
    'Lead ' || i,
    'lead' || i || '@example.com',
    CASE
        WHEN random() < 0.25 THEN 'organic'
        WHEN random() < 0.50 THEN 'paid'
        WHEN random() < 0.70 THEN 'referral'
        WHEN random() < 0.85 THEN 'event'
        ELSE 'content'
    END,
    CASE WHEN random() < 0.7 THEN (random() * 29 + 1)::int ELSE NULL END,
    CASE
        WHEN random() < 0.15 THEN 'converted'
        WHEN random() < 0.35 THEN 'qualified'
        WHEN random() < 0.55 THEN 'contacted'
        WHEN random() < 0.80 THEN 'new'
        ELSE 'lost'
    END,
    (random() * 100)::int,
    ('2025-04-01'::date + (random() * 365)::int),
    CASE WHEN random() < 0.15 THEN ('2025-04-01'::date + (random() * 365)::int + 15) ELSE NULL END
FROM generate_series(1, 500) AS i;

-- Ad Spend (180 rows — daily by platform)
CREATE TABLE demo_novatech.ad_spend (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(50),
    campaign_id INTEGER REFERENCES demo_novatech.campaigns(id),
    date DATE NOT NULL,
    spend NUMERIC(10,2),
    impressions INTEGER,
    clicks INTEGER,
    cpc NUMERIC(6,2),
    cpa NUMERIC(8,2)
);

INSERT INTO demo_novatech.ad_spend (platform, campaign_id, date, spend, impressions, clicks, cpc, cpa)
SELECT
    CASE WHEN random() < 0.4 THEN 'Google Ads' WHEN random() < 0.7 THEN 'LinkedIn' WHEN random() < 0.9 THEN 'Facebook' ELSE 'Twitter' END,
    (random() * 29 + 1)::int,
    ('2025-10-01'::date + (i % 180)),
    (random() * 800 + 50)::numeric(10,2),
    (random() * 15000 + 500)::int,
    (random() * 500 + 10)::int,
    (random() * 8 + 0.5)::numeric(6,2),
    (random() * 150 + 10)::numeric(8,2)
FROM generate_series(1, 180) AS i;

-- Conversion Funnel (120 rows — monthly by stage)
CREATE TABLE demo_novatech.conversion_funnel (
    id SERIAL PRIMARY KEY,
    stage VARCHAR(50),  -- visitors, signups, trials, qualified, closed
    date DATE,
    count INTEGER,
    conversion_rate NUMERIC(5,2),
    campaign_id INTEGER REFERENCES demo_novatech.campaigns(id)
);

INSERT INTO demo_novatech.conversion_funnel (stage, date, count, conversion_rate, campaign_id)
SELECT
    s.stage,
    ('2025-04-01'::date + (m * 30)),
    CASE
        WHEN s.stage = 'visitors' THEN (random() * 50000 + 20000)::int
        WHEN s.stage = 'signups' THEN (random() * 2000 + 500)::int
        WHEN s.stage = 'trials' THEN (random() * 500 + 100)::int
        WHEN s.stage = 'qualified' THEN (random() * 150 + 30)::int
        ELSE (random() * 40 + 5)::int
    END,
    CASE
        WHEN s.stage = 'visitors' THEN 100.0
        WHEN s.stage = 'signups' THEN (random() * 5 + 2)::numeric(5,2)
        WHEN s.stage = 'trials' THEN (random() * 30 + 15)::numeric(5,2)
        WHEN s.stage = 'qualified' THEN (random() * 40 + 20)::numeric(5,2)
        ELSE (random() * 35 + 15)::numeric(5,2)
    END,
    NULL
FROM generate_series(0, 11) AS m,
     (VALUES ('visitors'), ('signups'), ('trials'), ('qualified'), ('closed')) AS s(stage);

-- ════════════════════════════════════════════════════════════
-- ENGINEERING DEPARTMENT
-- ════════════════════════════════════════════════════════════

-- Deployments (100 rows)
CREATE TABLE demo_novatech.deployments (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100),
    version VARCHAR(20),
    environment VARCHAR(20),  -- production, staging, development
    status VARCHAR(20),  -- success, failed, rolled_back
    deployed_by VARCHAR(100),
    deployed_at TIMESTAMP,
    rollback_count INTEGER DEFAULT 0,
    duration_minutes INTEGER
);

INSERT INTO demo_novatech.deployments (service_name, version, environment, status, deployed_by, deployed_at, rollback_count, duration_minutes)
SELECT
    CASE (random() * 5)::int
        WHEN 0 THEN 'api-gateway'
        WHEN 1 THEN 'auth-service'
        WHEN 2 THEN 'data-pipeline'
        WHEN 3 THEN 'web-app'
        WHEN 4 THEN 'ml-engine'
        ELSE 'notification-service'
    END,
    'v' || (2 + (random() * 2)::int) || '.' || (random() * 20)::int || '.' || (random() * 50)::int,
    CASE WHEN random() < 0.6 THEN 'production' WHEN random() < 0.85 THEN 'staging' ELSE 'development' END,
    CASE WHEN random() < 0.85 THEN 'success' WHEN random() < 0.95 THEN 'failed' ELSE 'rolled_back' END,
    CASE (random() * 4)::int WHEN 0 THEN 'priya.patel' WHEN 1 THEN 'liam.johnson' WHEN 2 THEN 'dev-bot' WHEN 3 THEN 'ci-pipeline' ELSE 'manual' END,
    '2025-04-01'::timestamp + (random() * 365 * 24 * 60)::int * interval '1 minute',
    CASE WHEN random() < 0.1 THEN 1 ELSE 0 END,
    (random() * 45 + 2)::int
FROM generate_series(1, 100);

-- Incidents (40 rows)
CREATE TABLE demo_novatech.incidents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(300),
    severity VARCHAR(10),  -- P1, P2, P3, P4
    status VARCHAR(20),  -- open, investigating, resolved, closed
    service_name VARCHAR(100),
    started_at TIMESTAMP,
    resolved_at TIMESTAMP,
    root_cause TEXT,
    impact_users INTEGER
);

INSERT INTO demo_novatech.incidents (title, severity, status, service_name, started_at, resolved_at, root_cause, impact_users) VALUES
('API Gateway timeout affecting all services', 'P1', 'resolved', 'api-gateway', '2025-10-15 14:30:00', '2025-10-15 16:45:00', 'Memory leak in connection pool', 15000),
('Authentication service intermittent failures', 'P1', 'resolved', 'auth-service', '2025-12-03 09:15:00', '2025-12-03 11:30:00', 'Redis cluster failover during maintenance', 8000),
('Data pipeline stalled — no data for 4 hours', 'P2', 'resolved', 'data-pipeline', '2026-01-20 02:00:00', '2026-01-20 06:15:00', 'Kafka partition rebalance after broker restart', 3000),
('ML predictions returning stale results', 'P2', 'resolved', 'ml-engine', '2026-02-10 11:00:00', '2026-02-10 14:00:00', 'Model cache not invalidated after retraining', 5000),
('Web app blank page on Firefox', 'P3', 'resolved', 'web-app', '2025-09-05 08:00:00', '2025-09-05 12:00:00', 'CSS grid bug in Firefox 128', 2000),
('Notification service sending duplicate emails', 'P3', 'resolved', 'notification-service', '2025-11-18 16:00:00', '2025-11-19 09:00:00', 'Idempotency key not checked in retry logic', 500),
('Database connection exhaustion during peak', 'P1', 'resolved', 'api-gateway', '2026-03-01 10:00:00', '2026-03-01 10:45:00', 'Connection pool too small for traffic spike', 12000),
('v3.0 rollout causing 500 errors', 'P1', 'resolved', 'web-app', '2025-10-28 09:00:00', '2025-10-28 13:00:00', 'Breaking schema migration in v3.0', 20000),
('SSL certificate expiry on staging', 'P4', 'resolved', 'api-gateway', '2025-08-20 06:00:00', '2025-08-20 07:30:00', 'Auto-renewal failed — manual renewal needed', 0),
('Search index corruption', 'P2', 'resolved', 'data-pipeline', '2026-03-15 03:00:00', '2026-03-15 08:00:00', 'Elasticsearch shard reallocation failure', 4000),
('High CPU on ML inference pods', 'P3', 'investigating', 'ml-engine', '2026-03-28 14:00:00', NULL, 'Investigating — possible model size regression', 1000),
('Login page slow (>5s) in EU region', 'P3', 'open', 'auth-service', '2026-04-01 08:00:00', NULL, NULL, 3500);

-- More incidents with random generation
INSERT INTO demo_novatech.incidents (title, severity, status, service_name, started_at, resolved_at, root_cause, impact_users)
SELECT
    'Automated alert: ' || CASE (random()*5)::int WHEN 0 THEN 'High error rate' WHEN 1 THEN 'Latency spike' WHEN 2 THEN 'Memory pressure' WHEN 3 THEN 'Disk usage' ELSE 'CPU throttling' END || ' on ' || CASE (random()*4)::int WHEN 0 THEN 'api-gateway' WHEN 1 THEN 'web-app' WHEN 2 THEN 'data-pipeline' ELSE 'ml-engine' END,
    CASE WHEN random() < 0.1 THEN 'P1' WHEN random() < 0.3 THEN 'P2' WHEN random() < 0.7 THEN 'P3' ELSE 'P4' END,
    'resolved',
    CASE (random()*4)::int WHEN 0 THEN 'api-gateway' WHEN 1 THEN 'web-app' WHEN 2 THEN 'data-pipeline' ELSE 'ml-engine' END,
    '2025-04-01'::timestamp + (random() * 365 * 24 * 60)::int * interval '1 minute',
    '2025-04-01'::timestamp + (random() * 365 * 24 * 60)::int * interval '1 minute' + (random() * 180 + 10)::int * interval '1 minute',
    'Auto-resolved by self-healing',
    (random() * 5000)::int
FROM generate_series(1, 28);

-- Bugs (150 rows)
CREATE TABLE demo_novatech.bugs (
    id SERIAL PRIMARY KEY,
    title VARCHAR(300),
    priority VARCHAR(20),  -- critical, high, medium, low
    status VARCHAR(20),  -- open, in_progress, resolved, closed, wont_fix
    component VARCHAR(100),
    reported_by VARCHAR(100),
    reported_date DATE,
    resolved_date DATE,
    sprint_id VARCHAR(50)
);

INSERT INTO demo_novatech.bugs (title, priority, status, component, reported_by, reported_date, resolved_date, sprint_id)
SELECT
    'BUG-' || i || ': ' || CASE (random()*8)::int WHEN 0 THEN 'UI alignment issue' WHEN 1 THEN 'Data not loading' WHEN 2 THEN 'Error on save' WHEN 3 THEN 'Performance regression' WHEN 4 THEN 'Incorrect calculation' WHEN 5 THEN 'Missing validation' WHEN 6 THEN 'Broken link' ELSE 'Unexpected behavior' END,
    CASE WHEN random() < 0.05 THEN 'critical' WHEN random() < 0.2 THEN 'high' WHEN random() < 0.6 THEN 'medium' ELSE 'low' END,
    CASE WHEN random() < 0.4 THEN 'closed' WHEN random() < 0.6 THEN 'resolved' WHEN random() < 0.75 THEN 'in_progress' WHEN random() < 0.95 THEN 'open' ELSE 'wont_fix' END,
    CASE (random()*5)::int WHEN 0 THEN 'frontend' WHEN 1 THEN 'backend' WHEN 2 THEN 'api' WHEN 3 THEN 'database' ELSE 'infrastructure' END,
    CASE (random()*4)::int WHEN 0 THEN 'priya.patel' WHEN 1 THEN 'liam.johnson' WHEN 2 THEN 'qa-bot' ELSE 'user-report' END,
    ('2025-04-01'::date + (random() * 365)::int),
    CASE WHEN random() < 0.6 THEN ('2025-04-01'::date + (random() * 365)::int + (random() * 14)::int) ELSE NULL END,
    'Sprint ' || ((random() * 24)::int + 1)
FROM generate_series(1, 150) AS i;

-- Sprint Velocity (24 sprints)
CREATE TABLE demo_novatech.sprint_velocity (
    id SERIAL PRIMARY KEY,
    sprint_name VARCHAR(50),
    sprint_start DATE,
    sprint_end DATE,
    planned_points INTEGER,
    completed_points INTEGER,
    team_size INTEGER,
    carry_over INTEGER
);

INSERT INTO demo_novatech.sprint_velocity (sprint_name, sprint_start, sprint_end, planned_points, completed_points, team_size, carry_over)
SELECT
    'Sprint ' || i,
    ('2025-04-01'::date + ((i-1) * 14)),
    ('2025-04-01'::date + ((i-1) * 14) + 13),
    (random() * 30 + 40)::int,
    (random() * 25 + 30)::int,
    CASE WHEN i > 18 THEN 12 ELSE 10 END,
    (random() * 8)::int
FROM generate_series(1, 24) AS i;

-- ════════════════════════════════════════════════════════════
-- OPERATIONS DEPARTMENT
-- ════════════════════════════════════════════════════════════

-- Support Tickets (400 rows)
CREATE TABLE demo_novatech.tickets (
    id SERIAL PRIMARY KEY,
    subject VARCHAR(300),
    category VARCHAR(50),  -- technical, billing, feature_request, onboarding, general
    priority VARCHAR(20),  -- urgent, high, normal, low
    status VARCHAR(20),  -- open, in_progress, pending, resolved, closed
    created_date DATE,
    resolved_date DATE,
    assigned_to VARCHAR(100),
    sla_met BOOLEAN
);

INSERT INTO demo_novatech.tickets (subject, category, priority, status, created_date, resolved_date, assigned_to, sla_met)
SELECT
    'TICKET-' || i || ': ' || CASE (random()*6)::int
        WHEN 0 THEN 'Cannot login to dashboard'
        WHEN 1 THEN 'Invoice discrepancy'
        WHEN 2 THEN 'Feature request: export to PDF'
        WHEN 3 THEN 'Data sync not working'
        WHEN 4 THEN 'Slow performance on reports'
        ELSE 'Need help with configuration'
    END,
    CASE (random()*4)::int WHEN 0 THEN 'technical' WHEN 1 THEN 'billing' WHEN 2 THEN 'feature_request' WHEN 3 THEN 'onboarding' ELSE 'general' END,
    CASE WHEN random() < 0.05 THEN 'urgent' WHEN random() < 0.2 THEN 'high' WHEN random() < 0.7 THEN 'normal' ELSE 'low' END,
    CASE WHEN random() < 0.35 THEN 'closed' WHEN random() < 0.55 THEN 'resolved' WHEN random() < 0.7 THEN 'in_progress' WHEN random() < 0.85 THEN 'pending' ELSE 'open' END,
    ('2025-04-01'::date + (random() * 365)::int),
    CASE WHEN random() < 0.7 THEN ('2025-04-01'::date + (random() * 365)::int + (random() * 5)::int) ELSE NULL END,
    CASE (random()*3)::int WHEN 0 THEN 'james.wilson' WHEN 1 THEN 'support-team-1' WHEN 2 THEN 'support-team-2' ELSE 'unassigned' END,
    random() < 0.82
FROM generate_series(1, 400) AS i;

-- SLA Metrics (24 months)
CREATE TABLE demo_novatech.sla_metrics (
    id SERIAL PRIMARY KEY,
    service VARCHAR(100),
    month INTEGER,
    year INTEGER,
    target_uptime NUMERIC(5,2),
    actual_uptime NUMERIC(5,2),
    breaches INTEGER,
    avg_response_hours NUMERIC(5,2)
);

INSERT INTO demo_novatech.sla_metrics (service, month, year, target_uptime, actual_uptime, breaches, avg_response_hours)
SELECT
    s.service,
    ((m - 1) % 12) + 1,
    2025 + ((m - 1) / 12),
    99.90,
    (99.0 + random() * 1.0)::numeric(5,2),
    (random() * 5)::int,
    (random() * 3 + 0.5)::numeric(5,2)
FROM generate_series(1, 12) AS m,
     (VALUES ('API Gateway'), ('Web Application'), ('Data Pipeline'), ('ML Engine')) AS s(service);

-- Vendor Costs (15 vendors)
CREATE TABLE demo_novatech.vendor_costs (
    id SERIAL PRIMARY KEY,
    vendor_name VARCHAR(200),
    category VARCHAR(50),
    contract_value NUMERIC(12,2),
    monthly_cost NUMERIC(10,2),
    start_date DATE,
    renewal_date DATE,
    status VARCHAR(20)  -- active, expiring, expired, under_review
);

INSERT INTO demo_novatech.vendor_costs (vendor_name, category, contract_value, monthly_cost, start_date, renewal_date, status) VALUES
('Amazon Web Services', 'Cloud Infrastructure', 480000, 40000, '2024-01-01', '2026-01-01', 'active'),
('Google Cloud Platform', 'Data & AI', 180000, 15000, '2024-06-01', '2026-06-01', 'active'),
('Datadog', 'Monitoring', 60000, 5000, '2024-03-01', '2026-03-01', 'active'),
('Snowflake', 'Data Warehouse', 120000, 10000, '2024-09-01', '2025-09-01', 'expiring'),
('HubSpot', 'CRM', 48000, 4000, '2024-01-15', '2026-01-15', 'active'),
('Jira', 'Project Management', 18000, 1500, '2024-04-01', '2026-04-01', 'active'),
('Slack', 'Communication', 24000, 2000, '2024-01-01', '2026-01-01', 'active'),
('Zendesk', 'Customer Support', 36000, 3000, '2024-07-01', '2026-07-01', 'active'),
('Stripe', 'Payments', 0, 8500, '2023-01-01', NULL, 'active'),
('Auth0', 'Authentication', 30000, 2500, '2024-05-01', '2026-05-01', 'active'),
('Cloudflare', 'CDN & Security', 24000, 2000, '2024-08-01', '2026-08-01', 'active'),
('SendGrid', 'Email Delivery', 12000, 1000, '2024-02-01', '2025-02-01', 'expired'),
('Figma', 'Design', 9600, 800, '2024-06-01', '2026-06-01', 'active'),
('GitHub Enterprise', 'Source Control', 42000, 3500, '2024-01-01', '2026-01-01', 'active'),
('PagerDuty', 'Incident Management', 15000, 1250, '2024-09-01', '2025-09-01', 'under_review');

-- Inventory (60 items)
CREATE TABLE demo_novatech.inventory (
    id SERIAL PRIMARY KEY,
    item_name VARCHAR(200),
    category VARCHAR(50),
    quantity INTEGER,
    unit_cost NUMERIC(10,2),
    reorder_point INTEGER,
    last_restocked DATE,
    warehouse VARCHAR(50)
);

INSERT INTO demo_novatech.inventory (item_name, category, quantity, unit_cost, reorder_point, last_restocked, warehouse)
SELECT
    CASE (random()*9)::int
        WHEN 0 THEN 'Dell Laptop XPS 15'
        WHEN 1 THEN 'Apple MacBook Pro 16'
        WHEN 2 THEN 'Monitor LG 27" 4K'
        WHEN 3 THEN 'USB-C Docking Station'
        WHEN 4 THEN 'Wireless Keyboard'
        WHEN 5 THEN 'Ergonomic Chair'
        WHEN 6 THEN 'Standing Desk'
        WHEN 7 THEN 'Noise Cancelling Headset'
        WHEN 8 THEN 'Webcam HD Pro'
        ELSE 'Network Switch'
    END || ' (Batch ' || i || ')',
    CASE WHEN random() < 0.5 THEN 'IT Equipment' WHEN random() < 0.8 THEN 'Office Furniture' ELSE 'Networking' END,
    (random() * 50 + 1)::int,
    (random() * 2000 + 50)::numeric(10,2),
    (random() * 10 + 2)::int,
    ('2025-04-01'::date + (random() * 365)::int),
    CASE WHEN random() < 0.5 THEN 'US-East' WHEN random() < 0.8 THEN 'EU-West' ELSE 'APAC' END
FROM generate_series(1, 60) AS i;

-- ════════════════════════════════════════════════════════════
-- VERIFY
-- ════════════════════════════════════════════════════════════

DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '=== NovaTech Demo Data Created ===';
    FOR r IN
        SELECT table_name,
               (xpath('/row/cnt/text()',
                query_to_xml(format('SELECT count(*) as cnt FROM demo_novatech.%I', table_name), false, false, ''))
               )[1]::text AS row_count
        FROM information_schema.tables
        WHERE table_schema = 'demo_novatech'
        ORDER BY table_name
    LOOP
        RAISE NOTICE '  % : % rows', rpad(r.table_name, 20), r.row_count;
    END LOOP;
END $$;
