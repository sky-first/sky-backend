-- ─────────────────────────────────────────────────────────────────────
-- Public demo dataset — INSERT phase (idempotent re-seed).
-- Run AFTER scripts/demo/seed_multi_schema.sql which builds the schemas.
-- ─────────────────────────────────────────────────────────────────────

-- Self-contained reset — sequences AND data wiped, so every re-run
-- yields the same IDs (1..N) and FK references match deterministically.
TRUNCATE
    crm.activities, crm.deals, crm.opportunities, crm.contacts, crm.accounts, crm.sales_reps,
    marketing.email_events, marketing.ad_spend, marketing.mqls, marketing.leads, marketing.campaigns, marketing.channels,
    finance.costs, finance.mrr_snapshots, finance.invoices, finance.subscriptions,
    web_analytics.conversions, web_analytics.sessions, web_analytics.utm_sources,
    product_usage.accounts_health, product_usage.feature_adoption, product_usage.events
RESTART IDENTITY CASCADE;

BEGIN;
SET search_path = public;

-- ─── crm.sales_reps (20) ─────────────────────────────────────────────
INSERT INTO crm.sales_reps (name, email, region, quota, hired_on) VALUES
('Alex Chen',       'alex.chen@acme.example',     'NA',    1500000, '2023-01-15'),
('Maria Silva',     'maria.silva@acme.example',   'LATAM', 1200000, '2023-02-08'),
('Tom Wright',      'tom.wright@acme.example',    'EMEA',  1400000, '2023-03-22'),
('Priya Sharma',    'priya.sharma@acme.example',  'APAC',  1100000, '2023-04-11'),
('Liam O''Brien',   'liam.obrien@acme.example',   'EMEA',  1300000, '2023-05-30'),
('Yuki Tanaka',     'yuki.tanaka@acme.example',   'APAC',  1100000, '2023-06-18'),
('Sofia Rossi',     'sofia.rossi@acme.example',   'EMEA',  1250000, '2023-07-05'),
('Marcus Bennett',  'marcus.bennett@acme.example','NA',    1500000, '2023-08-14'),
('Helena Vargas',   'helena.vargas@acme.example', 'LATAM', 1200000, '2023-09-20'),
('Diego Torres',    'diego.torres@acme.example',  'LATAM', 1100000, '2023-10-03'),
('Olivia Park',     'olivia.park@acme.example',   'NA',    1450000, '2023-11-12'),
('Hassan Karim',    'hassan.karim@acme.example',  'EMEA',  1300000, '2023-12-01'),
('Mei-Lin Wong',    'meilin.wong@acme.example',   'APAC',  1150000, '2024-01-15'),
('Ravi Patel',      'ravi.patel@acme.example',    'APAC',  1100000, '2024-02-19'),
('Emma Lindberg',   'emma.lindberg@acme.example', 'EMEA',  1250000, '2024-03-08'),
('Noah Kim',        'noah.kim@acme.example',      'NA',    1400000, '2024-04-12'),
('Lucia Cardoso',   'lucia.cardoso@acme.example', 'LATAM', 1100000, '2024-05-25'),
('Jacob Müller',    'jacob.muller@acme.example',  'EMEA',  1300000, '2024-06-30'),
('Aiko Nakamura',   'aiko.nakamura@acme.example', 'APAC',  1100000, '2024-07-14'),
('Carlos Mendes',   'carlos.mendes@acme.example', 'LATAM', 1200000, '2024-08-22');

-- ─── crm.accounts (1000) — generated, with realistic cross-domain spread ─
DO $$
DECLARE
    v_industries TEXT[] := ARRAY['SaaS','E-commerce','Healthcare','FinTech','EdTech','Manufacturing','Logistics','Media','Real Estate','Energy','Retail','Telecom','Travel','Insurance','Gaming','BioTech','Construction','Legal','Marketing Agency','Hospitality'];
    v_countries TEXT[] := ARRAY['US','UK','DE','FR','BR','MX','CA','AU','JP','SG','IN','ES','IT','NL','SE','PL','AE','ZA','KR','CL'];
    v_plans TEXT[] := ARRAY['starter','pro','business','enterprise'];
    v_first_names TEXT[] := ARRAY['Acme','Globex','Initech','Umbrella','Wonka','Wayne','Stark','Tyrell','Aperture','Pied','Hooli','Bluth','Soylent','Cyberdyne','Vandelay','Gekko','Massive','Veridian','Reynholm','Oscorp','LexCorp','Daily','Spacely','Cogswell','Nakatomi','Yoyodyne','Krusty','Springfield','Globo','Sirius','Buy','Rekall','Sterling','Wernham','Dunder','Black','Pinwheel','Olivia','Helios','Northwind','Contoso','Fabrikam','Apollo','Atlas','Beacon','Cascade','Crimson','Dynamo','Echo','Falcon','Forge','Fusion','Granite','Helix','Ironclad','Lighthouse','Luminous','Meridian','Nimbus','Onyx','Phoenix','Polaris','Quartz','Quantum','Radiant','Saber','Sapphire','Stellar','Summit','Synthwave','Tempest','Titan','Topaz','Vanguard','Vector','Verdant','Vertex','Voyager','Zenith','Aurora','Bedrock','Cipher','Cobalt','Dragon','Eclipse','Ember','Frost','Glacier','Halo','Hyperion','Ion','Jade','Keystone','Krypton','Lunar','Magnum','Nova','Obsidian','Orbit','Pinnacle','Pulse'];
    v_suffixes TEXT[] := ARRAY['Corp','Inc','LLC','Industries','Group','Holdings','Partners','Labs','Systems','Solutions','Technologies','Ventures','Networks','Dynamics','Logistics','Capital','Studios','Works','Co','Enterprises'];
    v_roles TEXT[] := ARRAY['CEO','CFO','CTO','COO','VP Sales','VP Marketing','Director of Ops','Head of Data','Senior Analyst','Marketing Manager','Sales Manager','Product Manager','CSM','Engineering Lead','HR Director'];

    v_id INT;
    v_industry TEXT;
    v_country TEXT;
    v_plan TEXT;
    v_first TEXT;
    v_suffix TEXT;
    v_name TEXT;
    v_domain TEXT;
    v_employees INT;
    v_signup DATE;
    v_arr NUMERIC;
    v_rep_id INT;
    v_dup_count INT := 0;
BEGIN
    FOR v_id IN 1..1000 LOOP
        v_industry := v_industries[1 + (random() * (array_length(v_industries,1)-1))::INT];
        v_country  := v_countries [1 + (random() * (array_length(v_countries ,1)-1))::INT];
        v_plan     := v_plans     [1 + (random() * (array_length(v_plans     ,1)-1))::INT];
        v_first    := v_first_names[1 + (random() * (array_length(v_first_names,1)-1))::INT];
        v_suffix   := v_suffixes  [1 + (random() * (array_length(v_suffixes  ,1)-1))::INT];
        v_name     := v_first || ' ' || v_suffix;
        v_domain   := lower(replace(v_first, '''', '')) || '-' || lower(v_suffix) || v_id || '.example';
        v_employees := CASE v_plan
                        WHEN 'enterprise' THEN 500 + (random()*4500)::INT
                        WHEN 'business'   THEN 50  + (random()*450)::INT
                        WHEN 'pro'        THEN 10  + (random()*90)::INT
                        ELSE 1 + (random()*9)::INT END;
        v_arr := CASE v_plan
                    WHEN 'enterprise' THEN 80000 + (random()*120000)::NUMERIC
                    WHEN 'business'   THEN 24000 + (random()*36000)::NUMERIC
                    WHEN 'pro'        THEN 6000  + (random()*6000)::NUMERIC
                    ELSE 1200 + (random()*1800)::NUMERIC END;
        v_signup := CURRENT_DATE - ((random() * 700)::INT || ' days')::INTERVAL;
        v_rep_id := 1 + (random()*19)::INT;

        BEGIN
            INSERT INTO crm.accounts (name, domain, industry, country, employees, plan, signup_date, arr, owner_rep_id)
            VALUES (v_name, v_domain, v_industry, v_country, v_employees, v_plan, v_signup, v_arr, v_rep_id);
        EXCEPTION WHEN unique_violation THEN
            v_dup_count := v_dup_count + 1;
        END;
    END LOOP;
    RAISE NOTICE 'crm.accounts seeded (% duplicates skipped)', v_dup_count;
END $$;

-- ─── crm.contacts — 1-5 per account ─────────────────────────────────
DO $$
DECLARE
    v_acc RECORD;
    v_n INT;
    v_first TEXT[] := ARRAY['Alice','Bob','Carlos','Diana','Eduardo','Fernanda','Gabriel','Helena','Ivan','Julia','Kenji','Laura','Marco','Nadia','Oscar','Petra','Qing','Rafael','Sofia','Theo','Uma','Vincent','Wei','Ximena','Yann','Zoe','Aarav','Bianca','Chen','Daniela','Elena','Felix','Grace','Hugo','Isabella','Jack','Khalil','Lina','Mateus','Naomi','Omar','Pablo','Quincy','Rohan','Saskia','Tomas','Ursula','Viktor','Willow','Yusuf','Zara'];
    v_last TEXT[] := ARRAY['Smith','Garcia','Lopez','Silva','Müller','Tanaka','Rossi','Sharma','Park','O''Brien','Bennett','Vargas','Torres','Karim','Wong','Patel','Lindberg','Kim','Cardoso','Mendes','Nakamura','Schmidt','Costa','Andersen','Ivanov','Zhang','Yamamoto','Singh','Beaumont','Costa','Almeida','Petersen','Olsen','Klein','Romano','Marquez','Espinoza','Rocha','Macedo','Brito','Castillo','Ferreira','Pessoa','Nguyen','Tran','Hassan'];
    v_roles TEXT[] := ARRAY['CEO','CFO','CTO','COO','VP Sales','VP Marketing','Director of Operations','Head of Data','Senior Analyst','Marketing Manager','Sales Manager','Product Manager','CSM','Engineering Lead','HR Director','Office Manager','Procurement Lead'];
    v_first_pick TEXT;
    v_last_pick TEXT;
    v_email TEXT;
    v_role TEXT;
    v_created TIMESTAMPTZ;
BEGIN
    FOR v_acc IN SELECT id, domain, signup_date FROM crm.accounts LOOP
        FOR v_n IN 1..(1 + (random()*4)::INT) LOOP
            v_first_pick := v_first[1 + (random() * (array_length(v_first,1)-1))::INT];
            v_last_pick  := v_last [1 + (random() * (array_length(v_last ,1)-1))::INT];
            v_role       := v_roles[1 + (random() * (array_length(v_roles,1)-1))::INT];
            v_email      := lower(v_first_pick) || '.' || lower(replace(v_last_pick, '''', '')) || v_acc.id || '_' || v_n || '@' || v_acc.domain;
            v_created    := v_acc.signup_date::TIMESTAMPTZ + ((random()*30)::INT || ' days')::INTERVAL;
            INSERT INTO crm.contacts (account_id, name, email, role, created_at)
            VALUES (v_acc.id, v_first_pick || ' ' || v_last_pick, v_email, v_role, v_created)
            ON CONFLICT (email) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- ─── marketing.channels ─────────────────────────────────────────────
INSERT INTO marketing.channels (name, category, is_paid) VALUES
('Google Search Ads',  'paid',     TRUE),
('LinkedIn Ads',       'paid',     TRUE),
('Facebook Ads',       'paid',     TRUE),
('Twitter Ads',        'paid',     TRUE),
('Organic Search',     'organic',  FALSE),
('Direct',             'organic',  FALSE),
('Referral Program',   'referral', FALSE),
('Content Marketing',  'content',  FALSE),
('Cold Outbound',      'outbound', FALSE),
('Trade Shows',        'events',   TRUE);

-- ─── marketing.campaigns (50) ───────────────────────────────────────
DO $$
DECLARE
    v_themes TEXT[] := ARRAY['Q1 SaaS Growth Sprint','Webinar Series H1','Enterprise ABM Push','Mid-Market Outreach','Black Friday Promo','Product Launch Wave','Customer Success Story','LinkedIn Thought Leadership','SEO Pillar Pages','Trade Show Booth','Competitor Conquest','Referral Boost','Annual Industry Report','Free Trial Funnel','Demo Request Push','Free Tool Launch','Email Reactivation','LATAM Expansion','APAC Pilot','Healthcare Vertical','Fintech Vertical','Manufacturing Outreach','EdTech Bundle','Year-End Review','Pricing Test','Brand Awareness','Influencer Co-marketing','Podcast Sponsorship','Newsletter Sponsorship','Partner Co-sell'];
    v_status TEXT[] := ARRAY['active','active','active','completed','completed','completed','planned','paused','cancelled'];
    v_n INT;
    v_theme TEXT;
    v_channel_id INT;
    v_start DATE;
    v_end DATE;
    v_budget NUMERIC;
    v_status_pick TEXT;
BEGIN
    FOR v_n IN 1..50 LOOP
        v_theme := v_themes[1 + (random() * (array_length(v_themes,1)-1))::INT] || ' #' || v_n;
        v_channel_id := 1 + (random()*9)::INT;
        v_start := CURRENT_DATE - ((random() * 400)::INT || ' days')::INTERVAL;
        v_end   := v_start + (30 + (random()*60)::INT || ' days')::INTERVAL;
        v_budget := 5000 + (random() * 95000)::NUMERIC;
        v_status_pick := v_status[1 + (random() * (array_length(v_status,1)-1))::INT];
        INSERT INTO marketing.campaigns (name, channel_id, start_date, end_date, budget, status)
        VALUES (v_theme, v_channel_id, v_start, v_end, v_budget, v_status_pick);
    END LOOP;
END $$;

-- ─── marketing.leads (5000) — half from campaigns, half from organic ─
DO $$
DECLARE
    v_first TEXT[] := ARRAY['Alice','Bob','Carlos','Diana','Eduardo','Fernanda','Gabriel','Helena','Ivan','Julia','Kenji','Laura','Marco','Nadia','Oscar','Petra','Rafael','Sofia','Theo','Uma','Vincent','Wei','Ximena','Yann','Zoe'];
    v_last TEXT[] := ARRAY['Smith','Garcia','Lopez','Silva','Tanaka','Rossi','Sharma','Park','Bennett','Vargas','Torres','Karim','Wong','Patel','Lindberg','Kim','Cardoso','Mendes','Nakamura','Schmidt'];
    v_titles TEXT[] := ARRAY['Director','Senior Manager','Manager','VP','CEO','CFO','Head of','Lead','Specialist','Analyst','Consultant','Owner'];
    v_companies TEXT[] := ARRAY['Acme Co','Globex Inc','Initech LLC','Umbrella Corp','Wonka Industries','Stark Industries','Hooli','Pied Piper','Aperture Science','Black Mesa','Apollo Labs','Atlas Group','Beacon Networks','Cascade Partners','Crimson Tech','Dynamo Solutions','Echo Systems','Falcon Holdings','Forge Industries','Fusion Ventures'];
    v_status_dist TEXT[] := ARRAY['new','new','new','working','working','mql','mql','sql','converted','lost'];
    v_n INT;
    v_first_pick TEXT;
    v_last_pick TEXT;
    v_email TEXT;
    v_company TEXT;
    v_title TEXT;
    v_camp_id INT;
    v_score INT;
    v_status TEXT;
    v_created TIMESTAMPTZ;
    v_converted_acc INT;
    v_converted_at TIMESTAMPTZ;
BEGIN
    FOR v_n IN 1..5000 LOOP
        v_first_pick := v_first[1 + (random() * (array_length(v_first,1)-1))::INT];
        v_last_pick  := v_last [1 + (random() * (array_length(v_last ,1)-1))::INT];
        v_company    := v_companies[1 + (random() * (array_length(v_companies,1)-1))::INT];
        v_title      := v_titles[1 + (random() * (array_length(v_titles,1)-1))::INT];
        v_email      := lower(v_first_pick) || '.' || lower(v_last_pick) || v_n || '@lead-' || v_n || '.example';
        v_camp_id    := CASE WHEN random() < 0.6 THEN 1 + (random()*49)::INT ELSE NULL END;
        v_score      := (random() * 100)::INT;
        v_status     := v_status_dist[1 + (random() * (array_length(v_status_dist,1)-1))::INT];
        v_created    := NOW() - ((random() * 365)::INT || ' days')::INTERVAL;
        v_converted_acc := NULL;
        v_converted_at := NULL;
        IF v_status = 'converted' AND random() < 0.9 THEN
            v_converted_acc := 1 + (random()*999)::INT;
            v_converted_at := v_created + ((random()*30)::INT || ' days')::INTERVAL;
        END IF;
        INSERT INTO marketing.leads (email, full_name, company, title, source_campaign_id, score, status, created_at, converted_account_id, converted_at)
        VALUES (v_email, v_first_pick || ' ' || v_last_pick, v_company, v_title, v_camp_id, v_score, v_status, v_created, v_converted_acc, v_converted_at)
        ON CONFLICT (email) DO NOTHING;
    END LOOP;
END $$;

-- ─── marketing.mqls — leads with score >= 60 OR status='mql/sql/converted' ─
INSERT INTO marketing.mqls (lead_id, qualified_at, score_at_qualification, rep_id)
SELECT
    l.id,
    l.created_at + (interval '1 day' * (1 + (random()*14)::INT)),
    GREATEST(l.score, 60),
    1 + (random()*19)::INT
FROM marketing.leads l
WHERE l.score >= 60 OR l.status IN ('mql','sql','converted')
ORDER BY random()
LIMIT 1500;

-- ─── marketing.ad_spend — ~12 daily rows per active/completed campaign ─
DO $$
DECLARE
    v_camp RECORD;
    v_day DATE;
    v_amount NUMERIC;
    v_imp INT;
    v_clk INT;
BEGIN
    FOR v_camp IN
        SELECT marketing.campaigns.id AS id,
               marketing.campaigns.channel_id,
               marketing.campaigns.start_date,
               marketing.campaigns.end_date,
               marketing.campaigns.budget
        FROM marketing.campaigns
        JOIN marketing.channels ON marketing.channels.id = marketing.campaigns.channel_id
        WHERE marketing.channels.is_paid = TRUE
          AND marketing.campaigns.status IN ('active','completed','paused')
    LOOP
        FOR v_day IN
            SELECT generate_series(v_camp.start_date, LEAST(v_camp.end_date, CURRENT_DATE), '3 days'::INTERVAL)::DATE
        LOOP
            v_amount := v_camp.budget / 30 * (0.5 + random());
            v_imp := (v_amount * (50 + random()*150))::INT;
            v_clk := (v_imp * (0.005 + random()*0.025))::INT;
            INSERT INTO marketing.ad_spend (campaign_id, spend_date, amount, impressions, clicks)
            VALUES (v_camp.id, v_day, v_amount, v_imp, v_clk);
        END LOOP;
    END LOOP;
END $$;

-- ─── marketing.email_events — sample stream from email campaigns ─────
DO $$
DECLARE
    v_n INT;
    v_camp_id INT;
    v_email TEXT;
    v_event TEXT;
    v_at TIMESTAMPTZ;
    v_evt_dist TEXT[] := ARRAY['sent','sent','sent','sent','delivered','delivered','delivered','opened','opened','clicked','bounced','unsubscribed'];
BEGIN
    FOR v_n IN 1..5000 LOOP
        v_camp_id := 1 + (random()*49)::INT;
        v_email   := 'recipient' || v_n || '@example.com';
        v_event   := v_evt_dist[1 + (random()*(array_length(v_evt_dist,1)-1))::INT];
        v_at      := NOW() - ((random() * 200)::INT || ' days')::INTERVAL;
        INSERT INTO marketing.email_events (campaign_id, recipient_email, event_type, event_at)
        VALUES (v_camp_id, v_email, v_event, v_at);
    END LOOP;
END $$;

-- ─── crm.opportunities (2000) ───────────────────────────────────────
DO $$
DECLARE
    v_n INT;
    v_acc_id INT;
    v_contact_id INT;
    v_rep_id INT;
    v_amount NUMERIC;
    v_stage TEXT;
    v_stages TEXT[] := ARRAY['discovery','demo','proposal','negotiation','closed_won','closed_won','closed_lost','closed_lost'];
    v_expected DATE;
    v_actual DATE;
    v_created TIMESTAMPTZ;
BEGIN
    FOR v_n IN 1..2000 LOOP
        v_acc_id := 1 + (random()*999)::INT;
        SELECT id INTO v_contact_id FROM crm.contacts WHERE account_id = v_acc_id ORDER BY random() LIMIT 1;
        v_rep_id := 1 + (random()*19)::INT;
        v_amount := 5000 + (random() * 245000)::NUMERIC;
        v_stage  := v_stages[1 + (random() * (array_length(v_stages,1)-1))::INT];
        v_created := NOW() - ((random() * 365)::INT || ' days')::INTERVAL;
        v_expected := v_created::DATE + (30 + (random()*120)::INT || ' days')::INTERVAL;
        v_actual := CASE WHEN v_stage IN ('closed_won','closed_lost')
                         THEN v_created::DATE + ((random()*120)::INT || ' days')::INTERVAL
                         ELSE NULL END;
        INSERT INTO crm.opportunities (account_id, contact_id, owner_rep_id, name, amount, stage, expected_close_date, actual_close_date, created_at)
        VALUES (v_acc_id, v_contact_id, v_rep_id, 'Opportunity #' || v_n, v_amount, v_stage, v_expected, v_actual, v_created);
    END LOOP;
END $$;

-- ─── crm.deals (every closed_won opp) ───────────────────────────────
INSERT INTO crm.deals (opportunity_id, amount, closed_at)
SELECT id, amount, COALESCE(actual_close_date::TIMESTAMPTZ, NOW())
FROM crm.opportunities
WHERE stage = 'closed_won';

-- ─── crm.activities (10000) ─────────────────────────────────────────
DO $$
DECLARE
    v_n INT;
    v_acc_id INT;
    v_type TEXT;
    v_types TEXT[] := ARRAY['call','call','email','email','email','meeting','demo','note'];
    v_at TIMESTAMPTZ;
    v_rep_id INT;
BEGIN
    FOR v_n IN 1..10000 LOOP
        v_acc_id := 1 + (random()*999)::INT;
        v_type   := v_types[1 + (random()*(array_length(v_types,1)-1))::INT];
        v_at     := NOW() - ((random() * 365)::INT || ' days')::INTERVAL - ((random()*86400)::INT || ' seconds')::INTERVAL;
        v_rep_id := 1 + (random()*19)::INT;
        INSERT INTO crm.activities (account_id, type, occurred_at, rep_id)
        VALUES (v_acc_id, v_type, v_at, v_rep_id);
    END LOOP;
END $$;

-- ─── finance.subscriptions (one per account, 80% active) ─────────────
INSERT INTO finance.subscriptions (account_id, plan, mrr, started_at, status, cancelled_at)
SELECT
    a.id,
    a.plan,
    a.arr / 12,
    a.signup_date,
    CASE WHEN random() < 0.85 THEN 'active'
         WHEN random() < 0.92 THEN 'cancelled'
         WHEN random() < 0.97 THEN 'trialing'
         ELSE 'paused' END,
    CASE WHEN random() < 0.15 THEN a.signup_date + ((random()*500)::INT || ' days')::INTERVAL ELSE NULL END
FROM crm.accounts a
ON CONFLICT (account_id) DO NOTHING;

-- ─── finance.invoices (~5 per active subscription = ~4000) ──────────
DO $$
DECLARE
    v_sub RECORD;
    v_month INT;
    v_amount NUMERIC;
    v_issued DATE;
    v_paid DATE;
    v_status TEXT;
BEGIN
    FOR v_sub IN SELECT account_id, mrr, started_at FROM finance.subscriptions WHERE status = 'active' LIMIT 800 LOOP
        FOR v_month IN 1..(1 + (random()*5)::INT) LOOP
            v_issued := v_sub.started_at + ((v_month - 1) || ' months')::INTERVAL;
            IF v_issued > CURRENT_DATE THEN EXIT; END IF;
            v_amount := v_sub.mrr * (0.95 + random()*0.1);
            v_paid   := CASE WHEN random() < 0.92 THEN v_issued + ((random()*15)::INT || ' days')::INTERVAL ELSE NULL END;
            v_status := CASE WHEN v_paid IS NOT NULL THEN 'paid'
                             WHEN random() < 0.05 THEN 'overdue'
                             ELSE 'open' END;
            INSERT INTO finance.invoices (account_id, deal_id, amount, currency, issued_at, paid_at, status)
            SELECT v_sub.account_id, d.id, v_amount, 'USD', v_issued, v_paid, v_status
            FROM crm.opportunities o
            LEFT JOIN crm.deals d ON d.opportunity_id = o.id
            WHERE o.account_id = v_sub.account_id AND o.stage = 'closed_won'
            LIMIT 1;
            IF NOT FOUND THEN
                INSERT INTO finance.invoices (account_id, deal_id, amount, currency, issued_at, paid_at, status)
                VALUES (v_sub.account_id, NULL, v_amount, 'USD', v_issued, v_paid, v_status);
            END IF;
        END LOOP;
    END LOOP;
END $$;

-- ─── finance.mrr_snapshots (24 monthly) ─────────────────────────────
INSERT INTO finance.mrr_snapshots (snapshot_date, total_mrr, new_mrr, expansion_mrr, contraction_mrr, churn_mrr, customers_active, customers_new, customers_churned)
SELECT
    (CURRENT_DATE - (interval '1 month' * gs))::DATE,
    400000 + (gs * 5000) + (random()*20000),
    20000 + (random()*15000),
    5000 + (random()*8000),
    -2000 + (random()*1000),
    -3000 - (random()*4000),
    700 + gs * 5,
    25 + (random()*20)::INT,
    5 + (random()*15)::INT
FROM generate_series(0, 23) AS gs;

-- ─── finance.costs (200) ────────────────────────────────────────────
DO $$
DECLARE
    v_cats TEXT[] := ARRAY['payroll','infrastructure','marketing','sales','tools','office','travel','legal'];
    v_vendors TEXT[] := ARRAY['AWS','Azure','GCP','HubSpot','Salesforce','Slack','Notion','LinkedIn Ads','Google Ads','Datadog','Snowflake','Atlassian','GitHub','Zoom','Greenhouse','Bamboo HR','Stripe','Plaid','Twilio','SendGrid','Cloudflare','Auth0','PagerDuty','Sentry','Mixpanel'];
    v_dept TEXT[] := ARRAY['Engineering','Marketing','Sales','Customer Success','HR','Finance','Operations'];
    v_n INT;
BEGIN
    FOR v_n IN 1..200 LOOP
        INSERT INTO finance.costs (category, vendor, incurred_on, amount, department)
        VALUES (
            v_cats[1 + (random()*(array_length(v_cats,1)-1))::INT],
            v_vendors[1 + (random()*(array_length(v_vendors,1)-1))::INT],
            CURRENT_DATE - ((random()*400)::INT || ' days')::INTERVAL,
            500 + (random()*49500)::NUMERIC,
            v_dept[1 + (random()*(array_length(v_dept,1)-1))::INT]
        );
    END LOOP;
END $$;

-- ─── web_analytics.utm_sources ──────────────────────────────────────
INSERT INTO web_analytics.utm_sources (source, medium, campaign_name) VALUES
('google','cpc','search-brand'),
('google','organic',NULL),
('linkedin','cpc','enterprise-abm'),
('linkedin','organic',NULL),
('facebook','cpc','retargeting'),
('twitter','cpc','thought-leadership'),
('newsletter','email','weekly-roundup'),
('referral','referral',NULL),
('direct','none',NULL),
('youtube','video','product-launch'),
('producthunt','referral','launch'),
('hackernews','referral',NULL),
('reddit','referral',NULL),
('podcast','sponsorship','q1-tour'),
('webinar','content','data-stack');

-- ─── web_analytics.sessions (10000) ─────────────────────────────────
DO $$
DECLARE
    v_n INT;
    v_landing TEXT[] := ARRAY['/','/pricing','/product','/integrations','/blog','/customers','/about','/demo','/login','/signup'];
    v_devices TEXT[] := ARRAY['desktop','desktop','desktop','mobile','mobile','tablet'];
    v_countries TEXT[] := ARRAY['US','UK','DE','FR','BR','MX','CA','AU','JP','SG','IN','ES','IT','NL','SE','PL','AE','ZA'];
BEGIN
    FOR v_n IN 1..10000 LOOP
        INSERT INTO web_analytics.sessions (visitor_uuid, utm_source_id, landing_page, referrer, country, device_type, started_at, duration_seconds, converted)
        VALUES (
            gen_random_uuid(),
            CASE WHEN random()<0.7 THEN 1 + (random()*14)::INT ELSE NULL END,
            v_landing[1 + (random()*(array_length(v_landing,1)-1))::INT],
            CASE WHEN random()<0.5 THEN 'https://google.com/search' ELSE NULL END,
            v_countries[1 + (random()*(array_length(v_countries,1)-1))::INT],
            v_devices[1 + (random()*(array_length(v_devices,1)-1))::INT],
            NOW() - ((random()*180)::INT || ' days')::INTERVAL - ((random()*86400)::INT || ' seconds')::INTERVAL,
            10 + (random()*900)::INT,
            random() < 0.08
        );
    END LOOP;
END $$;

-- ─── web_analytics.conversions (subset of converted sessions) ────────
INSERT INTO web_analytics.conversions (session_id, goal, value, converted_at, converted_to_lead_id)
SELECT
    s.id,
    (ARRAY['signup','demo_request','contact','newsletter','download','trial'])[1 + (random()*5)::INT],
    50 + (random()*450)::NUMERIC,
    s.started_at + (s.duration_seconds || ' seconds')::INTERVAL,
    NULL
FROM web_analytics.sessions s
WHERE s.converted = TRUE;

-- ─── product_usage.events (10000) ───────────────────────────────────
DO $$
DECLARE
    v_n INT;
    v_event_types TEXT[] := ARRAY['login','dashboard_viewed','widget_created','dashboard_shared','export','chat_message','agent_run','metric_created','glossary_added','connection_added'];
    v_features TEXT[] := ARRAY['dashboards','chat_ai','agents','widgets','knowledge_metrics','knowledge_glossary','relationships','sharing','exports','integrations'];
BEGIN
    FOR v_n IN 1..10000 LOOP
        INSERT INTO product_usage.events (account_id, event_type, feature, occurred_at)
        VALUES (
            1 + (random()*999)::INT,
            v_event_types[1 + (random()*(array_length(v_event_types,1)-1))::INT],
            v_features[1 + (random()*(array_length(v_features,1)-1))::INT],
            NOW() - ((random()*60)::INT || ' days')::INTERVAL
        );
    END LOOP;
END $$;

-- ─── product_usage.feature_adoption (1 row per (account, feature)) ──
INSERT INTO product_usage.feature_adoption (account_id, feature_name, first_used_at, last_used_at, usage_count)
SELECT
    e.account_id,
    e.feature,
    MIN(e.occurred_at),
    MAX(e.occurred_at),
    COUNT(*)
FROM product_usage.events e
GROUP BY e.account_id, e.feature
ON CONFLICT (account_id, feature_name) DO NOTHING;

-- ─── product_usage.accounts_health (one snapshot per account) ───────
INSERT INTO product_usage.accounts_health (account_id, snapshot_date, health_score, churn_risk, last_login_at, dau_30d)
SELECT
    a.id,
    CURRENT_DATE,
    GREATEST(0, LEAST(100, 50 + (random()*60)::INT - 30)),
    CASE
        WHEN random() < 0.55 THEN 'low'
        WHEN random() < 0.80 THEN 'medium'
        WHEN random() < 0.94 THEN 'high'
        ELSE 'critical' END,
    NOW() - ((random()*30)::INT || ' days')::INTERVAL,
    1 + (random()*200)::INT
FROM crm.accounts a
ON CONFLICT (account_id, snapshot_date) DO NOTHING;

-- ─── Read-only grants for the app ───────────────────────────────────
GRANT USAGE ON SCHEMA crm           TO demo_reader;
GRANT USAGE ON SCHEMA marketing     TO demo_reader;
GRANT USAGE ON SCHEMA finance       TO demo_reader;
GRANT USAGE ON SCHEMA web_analytics TO demo_reader;
GRANT USAGE ON SCHEMA product_usage TO demo_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA crm           TO demo_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marketing     TO demo_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA finance       TO demo_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA web_analytics TO demo_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA product_usage TO demo_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA crm           GRANT SELECT ON TABLES TO demo_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA marketing     GRANT SELECT ON TABLES TO demo_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance       GRANT SELECT ON TABLES TO demo_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA web_analytics GRANT SELECT ON TABLES TO demo_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA product_usage GRANT SELECT ON TABLES TO demo_reader;

COMMIT;

-- Summary
SELECT 'crm.sales_reps'         AS table, count(*) FROM crm.sales_reps         UNION ALL
SELECT 'crm.accounts',                count(*) FROM crm.accounts               UNION ALL
SELECT 'crm.contacts',                count(*) FROM crm.contacts               UNION ALL
SELECT 'crm.opportunities',           count(*) FROM crm.opportunities          UNION ALL
SELECT 'crm.deals',                   count(*) FROM crm.deals                  UNION ALL
SELECT 'crm.activities',              count(*) FROM crm.activities             UNION ALL
SELECT 'marketing.channels',          count(*) FROM marketing.channels         UNION ALL
SELECT 'marketing.campaigns',         count(*) FROM marketing.campaigns        UNION ALL
SELECT 'marketing.leads',             count(*) FROM marketing.leads            UNION ALL
SELECT 'marketing.mqls',              count(*) FROM marketing.mqls             UNION ALL
SELECT 'marketing.ad_spend',          count(*) FROM marketing.ad_spend         UNION ALL
SELECT 'marketing.email_events',      count(*) FROM marketing.email_events     UNION ALL
SELECT 'finance.subscriptions',       count(*) FROM finance.subscriptions      UNION ALL
SELECT 'finance.invoices',            count(*) FROM finance.invoices           UNION ALL
SELECT 'finance.mrr_snapshots',       count(*) FROM finance.mrr_snapshots      UNION ALL
SELECT 'finance.costs',               count(*) FROM finance.costs              UNION ALL
SELECT 'web_analytics.utm_sources',   count(*) FROM web_analytics.utm_sources  UNION ALL
SELECT 'web_analytics.sessions',      count(*) FROM web_analytics.sessions     UNION ALL
SELECT 'web_analytics.conversions',   count(*) FROM web_analytics.conversions  UNION ALL
SELECT 'product_usage.events',        count(*) FROM product_usage.events       UNION ALL
SELECT 'product_usage.feature_adoption', count(*) FROM product_usage.feature_adoption UNION ALL
SELECT 'product_usage.accounts_health',  count(*) FROM product_usage.accounts_health;
