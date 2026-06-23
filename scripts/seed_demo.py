"""
NovaTech Demo Seed Script
=========================
Creates a complete demo deployment for the Sky platform:
- 7 users, 4 spaces, 8 crews
- 4 PostgreSQL connections (one per department)
- Strategy: pillars, objectives, OKRs, key results, initiatives
- Events: internal + external + trends
- Agents: 8 monitoring agents
- Cross-space relationships

Prerequisites:
  1. Backend running on port 8000
  2. seed_demo_tables.sql already executed (creates demo_novatech schema)
  3. PyJWT installed: pip install PyJWT

Usage:
  python scripts/seed_demo.py
  python scripts/seed_demo.py --force  # Delete and recreate everything
"""

import sys
import json
import datetime
import httpx
import jwt

# ════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════

API = "http://localhost:8000/api/v1"
JWT_SECRET = "217a0c91c59bfeec95a3de24c6c1a5132bbc349f8bed90f15ca30f70d726ca4c"
ADMIN_USER_ID = "b11c2d26-d9c8-4676-b96a-6cba2fc446b1"
ADMIN_EMAIL = "lucas.ventura@skyfirstlabs.com"

# Generate JWT token
TOKEN = jwt.encode(
    {
        "sub": ADMIN_USER_ID,
        "email": ADMIN_EMAIL,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "type": "access",
    },
    JWT_SECRET,
    algorithm="HS256",
)

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
CLIENT = httpx.Client(base_url=API, headers=HEADERS, timeout=30)

# Track created IDs
IDS = {}


def post(path, data, label):
    try:
        r = CLIENT.post(path, json=data)
        if r.status_code in (200, 201):
            obj = r.json()
            id_ = obj.get("id", "")
            print(f"  + {label} -> {str(id_)[:8]}...")
            return id_
        elif r.status_code == 307:
            # Redirect — try with trailing slash
            r = CLIENT.post(path + "/", json=data)
            if r.status_code in (200, 201):
                obj = r.json()
                id_ = obj.get("id", "")
                print(f"  + {label} -> {str(id_)[:8]}...")
                return id_
        print(f"  x FAIL ({r.status_code}): {label} -> {r.text[:100]}")
        return None
    except Exception as e:
        print(f"  x ERROR: {label} -> {e}")
        return None


def get_list(path):
    try:
        r = CLIENT.get(path)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("items", data.get("results", []))
    except:
        pass
    return []


# ════════════════════════════════════════════════════════════
print("=" * 60)
print("  NovaTech Demo Seed")
print("=" * 60)

# ── 1. SPACES ──────────────────────────────────────────────
print("\n--- Spaces ---")
SPACES = [
    {
        "name": "Finance",
        "description": "Financial operations, revenue, invoicing, and cash management",
        "color": "#10b981",
        "icon": "dollar-sign",
        "privacy": "private",
        "sensitivity": "internal",
    },
    {
        "name": "Marketing",
        "description": "Growth, campaigns, lead generation, and brand management",
        "color": "#8b5cf6",
        "icon": "megaphone",
        "privacy": "private",
        "sensitivity": "internal",
    },
    {
        "name": "Engineering",
        "description": "Product development, deployments, incidents, and sprint velocity",
        "color": "#3b82f6",
        "icon": "code",
        "privacy": "private",
        "sensitivity": "internal",
    },
    {
        "name": "Operations",
        "description": "Support tickets, SLA management, vendor costs, and inventory",
        "color": "#f59e0b",
        "icon": "settings",
        "privacy": "private",
        "sensitivity": "internal",
    },
]

# Check existing spaces
existing_spaces = get_list("/spaces/")
for sp in SPACES:
    existing = next((s for s in existing_spaces if s.get("name") == sp["name"]), None)
    if existing:
        IDS[f"space_{sp['name'].lower()}"] = existing["id"]
        print(f"  = {sp['name']} already exists -> {existing['id'][:8]}...")
    else:
        id_ = post("/spaces", sp, sp["name"])
        if id_:
            IDS[f"space_{sp['name'].lower()}"] = id_

# ── 2. CREWS ──────────────────────────────────────────────
print("\n--- Crews ---")
CREWS = [
    {"name": "Finance Leadership", "space": "finance", "description": "CFO and finance directors"},
    {
        "name": "Controllers",
        "space": "finance",
        "description": "Accounting and financial control team",
    },
    {
        "name": "Growth Team",
        "space": "marketing",
        "description": "Demand generation and growth marketing",
    },
    {"name": "Brand", "space": "marketing", "description": "Brand strategy and content marketing"},
    {
        "name": "Platform Team",
        "space": "engineering",
        "description": "Core product and API development",
    },
    {
        "name": "Infrastructure",
        "space": "engineering",
        "description": "DevOps, CI/CD, and cloud infrastructure",
    },
    {
        "name": "Operations",
        "space": "operations",
        "description": "Operational excellence and vendor management",
    },
    {
        "name": "Support",
        "space": "operations",
        "description": "Customer support and ticket management",
    },
]

existing_crews = get_list("/crews/")
for cr in CREWS:
    space_id = IDS.get(f"space_{cr['space']}")
    if not space_id:
        print(f"  x Skip {cr['name']} (no space)")
        continue
    existing = next((c for c in existing_crews if c.get("name") == cr["name"]), None)
    if existing:
        IDS[f"crew_{cr['name'].lower().replace(' ', '_')}"] = existing["id"]
        print(f"  = {cr['name']} already exists")
    else:
        id_ = post(
            "/crews",
            {"name": cr["name"], "description": cr["description"], "space_id": space_id},
            cr["name"],
        )
        if id_:
            IDS[f"crew_{cr['name'].lower().replace(' ', '_')}"] = id_

# ── 3. CONNECTIONS ─────────────────────────────────────────
print("\n--- Connections ---")
CONNECTIONS = [
    {
        "name": "NovaTech Finance DB",
        "space": "finance",
        "connector_id": "postgresql",
        "description": "Finance department database: invoices, payments, customers, revenue",
        "config": {
            "host": "localhost",
            "port": 5432,
            "database": "ai_saas_db",
            "username": "postgres",
            "password": "postgres",
            "schema": "demo_novatech",
        },
    },
    {
        "name": "NovaTech Marketing DB",
        "space": "marketing",
        "connector_id": "postgresql",
        "description": "Marketing database: campaigns, leads, ad spend, conversion funnels",
        "config": {
            "host": "localhost",
            "port": 5432,
            "database": "ai_saas_db",
            "username": "postgres",
            "password": "postgres",
            "schema": "demo_novatech",
        },
    },
    {
        "name": "NovaTech Engineering DB",
        "space": "engineering",
        "connector_id": "postgresql",
        "description": "Engineering database: deployments, incidents, bugs, sprint velocity",
        "config": {
            "host": "localhost",
            "port": 5432,
            "database": "ai_saas_db",
            "username": "postgres",
            "password": "postgres",
            "schema": "demo_novatech",
        },
    },
    {
        "name": "NovaTech Operations DB",
        "space": "operations",
        "connector_id": "postgresql",
        "description": "Operations database: support tickets, SLA metrics, vendor costs, inventory",
        "config": {
            "host": "localhost",
            "port": 5432,
            "database": "ai_saas_db",
            "username": "postgres",
            "password": "postgres",
            "schema": "demo_novatech",
        },
    },
]

existing_conns = get_list("/connections/")
for conn in CONNECTIONS:
    existing = next((c for c in existing_conns if c.get("name") == conn["name"]), None)
    if existing:
        IDS[f"conn_{conn['space']}"] = existing["id"]
        print(f"  = {conn['name']} already exists")
    else:
        id_ = post(
            "/connections",
            {
                "name": conn["name"],
                "connector_id": conn["connector_id"],
                "description": conn["description"],
                "config": conn["config"],
            },
            conn["name"],
        )
        if id_:
            IDS[f"conn_{conn['space']}"] = id_

# Link connections to spaces
print("\n--- Space-Connection Links ---")
for conn in CONNECTIONS:
    space_id = IDS.get(f"space_{conn['space']}")
    conn_id = IDS.get(f"conn_{conn['space']}")
    if space_id and conn_id:
        try:
            r = CLIENT.post(f"/spaces/{space_id}/connections/{conn_id}")
            if r.status_code in (200, 201, 409):
                print(f"  + {conn['space']} <-> {conn['name'][:20]}...")
            else:
                print(f"  x Link failed ({r.status_code}): {r.text[:80]}")
        except Exception as e:
            print(f"  x Link error: {e}")

# ── 4. STRATEGY ────────────────────────────────────────────
print("\n--- Strategy: Cycle ---")
cycle_id = post(
    "/strategy/cycles",
    {
        "name": "Q2 2026",
        "type": "quarterly",
        "start_date": "2026-04-01T00:00:00Z",
        "end_date": "2026-06-30T23:59:59Z",
        "status": "active",
    },
    "Q2 2026 Cycle",
)

print("\n--- Strategy: Pillars ---")
pillars = {}
for name, desc, color, space in [
    (
        "Revenue Growth",
        "Increase ARR and expand customer base across all tiers",
        "#10b981",
        "finance",
    ),
    (
        "Cost Optimization",
        "Reduce operational costs and improve margin efficiency",
        "#06b6d4",
        "finance",
    ),
    (
        "Customer Acquisition",
        "Drive qualified leads and optimize conversion rates",
        "#8b5cf6",
        "marketing",
    ),
    (
        "Brand Leadership",
        "Establish NovaTech as the leading platform in enterprise intelligence",
        "#ec4899",
        "marketing",
    ),
    (
        "Technical Excellence",
        "Maintain 99.9% uptime with fast, reliable deployments",
        "#3b82f6",
        "engineering",
    ),
    (
        "Operational Efficiency",
        "Streamline support operations and vendor management",
        "#f59e0b",
        "operations",
    ),
]:
    pid = post(
        "/strategy/pillars",
        {
            "name": name,
            "description": desc,
            "color": color,
            "priority": "high",
            "owner": "Leadership",
            "space_id": IDS.get(f"space_{space}"),
        },
        name,
    )
    if pid:
        pillars[name] = pid

print("\n--- Strategy: Objectives ---")
objectives = {}
OBJ_DATA = [
    (
        "Grow ARR to $15M by Q4 2026",
        "corporate",
        "on_track",
        "high",
        "Revenue Growth",
        "finance",
        2000000,
    ),
    (
        "Reduce churn rate below 3%",
        "corporate",
        "at_risk",
        "high",
        "Revenue Growth",
        "finance",
        500000,
    ),
    (
        "Achieve 500 qualified leads per month",
        "unit",
        "on_track",
        "high",
        "Customer Acquisition",
        "marketing",
        800000,
    ),
    (
        "Increase brand awareness score to 75",
        "unit",
        "on_track",
        "medium",
        "Brand Leadership",
        "marketing",
        300000,
    ),
    (
        "Maintain 99.95% uptime SLA",
        "unit",
        "on_track",
        "high",
        "Technical Excellence",
        "engineering",
        0,
    ),
    (
        "Deploy weekly with zero-downtime",
        "team",
        "at_risk",
        "medium",
        "Technical Excellence",
        "engineering",
        0,
    ),
    (
        "Achieve 90% SLA compliance",
        "unit",
        "on_track",
        "high",
        "Operational Efficiency",
        "operations",
        200000,
    ),
    (
        "Reduce average ticket resolution to 4 hours",
        "team",
        "on_track",
        "medium",
        "Operational Efficiency",
        "operations",
        150000,
    ),
]
for title, otype, status, priority, pillar, space, budget in OBJ_DATA:
    oid = post(
        "/strategy/objectives",
        {
            "type": otype,
            "title": title,
            "description": f"Strategic objective: {title}",
            "status": status,
            "priority": priority,
            "owner": "Leadership",
            "pillar_id": pillars.get(pillar),
            "space_id": IDS.get(f"space_{space}"),
            "budget": budget,
        },
        title[:40],
    )
    if oid:
        objectives[title[:30]] = oid

print("\n--- Strategy: OKRs ---")
# Insert OKRs directly via SQL (the API endpoint times out)
import subprocess

okr_sql = """
INSERT INTO strategy_okrs (id, objective_id, cycle_id, title, baseline, target, deadline, measurement_frequency, space_id, created_at, updated_at)
VALUES
"""
okr_values = []
obj_list = list(objectives.values())
okr_data = [
    ("Increase MRR from $800K to $1.1M", 800000, 1100000, "weekly", "finance"),
    ("Close 20 new enterprise deals", 0, 20, "weekly", "finance"),
    ("Reduce churn from 5% to 3%", 5, 3, "monthly", "finance"),
    ("Generate 500 MQLs per month", 200, 500, "weekly", "marketing"),
    ("Achieve 30% email open rate", 18, 30, "weekly", "marketing"),
    ("Reach 10K social media followers", 4000, 10000, "biweekly", "marketing"),
    ("Deploy 95% of PRs within 24h", 70, 95, "weekly", "engineering"),
    ("Reduce P1 incident MTTR to 30min", 120, 30, "weekly", "engineering"),
    ("Zero failed deployments in Q2", 5, 0, "weekly", "engineering"),
    ("Resolve 90% tickets within SLA", 75, 90, "weekly", "operations"),
    ("Reduce vendor costs by 10%", 100000, 90000, "monthly", "operations"),
]

for idx, (title, baseline, target, freq, space) in enumerate(okr_data):
    obj_id = obj_list[min(idx, len(obj_list) - 1)] if obj_list else None
    if obj_id and cycle_id:
        space_id = IDS.get(f"space_{space}")
        okr_values.append(
            f"(gen_random_uuid(), '{obj_id}', '{cycle_id}', '{title}', {baseline}, {target}, '2026-06-30', '{freq}', '{space_id}', NOW(), NOW())"
        )

if okr_values:
    full_sql = okr_sql + ",\n".join(okr_values) + " RETURNING id, title;"
    result = subprocess.run(
        [
            "docker",
            "exec",
            "sky_poc_postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "ai_saas_db",
            "-c",
            full_sql,
        ],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.strip().split("\n"):
        if "|" in line and "id" not in line and "---" not in line:
            parts = line.strip().split("|")
            if len(parts) >= 2:
                print(f"  + OKR: {parts[1].strip()[:40]} -> {parts[0].strip()[:8]}...")

# ── 5. SIGNAL EVENTS ──────────────────────────────────────
print("\n--- Events ---")
EVENTS = [
    (
        "INTERNAL",
        "budget-change",
        "EVENT",
        "Q2 budget approved with 15% increase for Engineering",
        "HIGH",
        "finance",
    ),
    (
        "INTERNAL",
        "audit",
        "EVENT",
        "Q1 financial audit completed — no material findings",
        "HIGH",
        "finance",
    ),
    (
        "INTERNAL",
        "product-launch",
        "EVENT",
        "NovaTech Platform v3.0 launched with AI features",
        "HIGH",
        "engineering",
    ),
    (
        "INTERNAL",
        "hiring",
        "EVENT",
        "5 new engineers hired — team at 45 people",
        "HIGH",
        "engineering",
    ),
    (
        "INTERNAL",
        "restructure",
        "SIGNAL",
        "Marketing team reorganized: Growth + Brand split",
        "MEDIUM",
        "marketing",
    ),
    (
        "EXTERNAL",
        "competitor",
        "SIGNAL",
        "DataBot raised $50M Series C — enterprise AI focus",
        "HIGH",
        "marketing",
    ),
    (
        "EXTERNAL",
        "regulatory",
        "EVENT",
        "EU AI Act compliance deadline: August 2026",
        "HIGH",
        "engineering",
    ),
    (
        "EXTERNAL",
        "market",
        "SIGNAL",
        "Enterprise AI spending grew 35% YoY per Gartner",
        "HIGH",
        "finance",
    ),
    (
        "TRENDS",
        "technology",
        "SIGNAL",
        "Multi-agent AI becoming mainstream in enterprise",
        "HIGH",
        "engineering",
    ),
    (
        "TRENDS",
        "market-shift",
        "HYPOTHESIS",
        "Customers prefer vertical AI over horizontal platforms",
        "MEDIUM",
        "marketing",
    ),
    (
        "TRENDS",
        "pricing",
        "HYPOTHESIS",
        "Usage-based pricing becoming standard in B2B SaaS",
        "MEDIUM",
        "finance",
    ),
    (
        "INTERNAL",
        "vendor",
        "EVENT",
        "New AWS contract signed — 20% volume discount",
        "HIGH",
        "operations",
    ),
    (
        "INTERNAL",
        "expansion",
        "EVENT",
        "Support team expanded from 8 to 12 people",
        "MEDIUM",
        "operations",
    ),
    (
        "EXTERNAL",
        "customer",
        "SIGNAL",
        "Top 3 enterprise customers requesting API access",
        "HIGH",
        "engineering",
    ),
]

for category, sub_type, nature, desc, confidence, space in EVENTS:
    post(
        "/signal-events/",
        {
            "category": category,
            "sub_type": sub_type,
            "nature": nature,
            "description": desc,
            "start_date": "2026-03-15T00:00:00Z",
            "confidence": confidence,
            "space_id": IDS.get(f"space_{space}"),
        },
        desc[:40],
    )

# ── 6. AGENTS ──────────────────────────────────────────────
print("\n--- Agents ---")
AGENTS = [
    (
        "Revenue Monitor",
        "financial_analyst",
        "space",
        "finance",
        "question",
        "What is our current MRR and how has it changed in the last 30 days?",
        "daily",
    ),
    (
        "Cash Flow Alert",
        "risk_radar",
        "space",
        "finance",
        "question",
        "Are there any overdue invoices that could affect cash flow?",
        "daily",
    ),
    (
        "Lead Quality Monitor",
        "growth_intelligence",
        "space",
        "marketing",
        "question",
        "What is the conversion rate from MQL to SQL this month vs last month?",
        "daily",
    ),
    (
        "CAC Tracker",
        "financial_analyst",
        "space",
        "marketing",
        "question",
        "What is our customer acquisition cost by channel?",
        "weekly",
    ),
    (
        "Deployment Monitor",
        "operations_monitor",
        "space",
        "engineering",
        "question",
        "How many deployments happened today and were there any failures?",
        "hourly",
    ),
    (
        "Error Tracker",
        "risk_radar",
        "space",
        "engineering",
        "question",
        "Are there any open P1 or P2 incidents?",
        "hourly",
    ),
    (
        "SLA Monitor",
        "operations_monitor",
        "space",
        "operations",
        "question",
        "What is our current SLA compliance rate and are any services below target?",
        "daily",
    ),
    (
        "Vendor Cost Alert",
        "financial_analyst",
        "space",
        "operations",
        "question",
        "Which vendor contracts are expiring in the next 90 days?",
        "weekly",
    ),
]

for name, archetype, scope, space, mtype, focus, freq in AGENTS:
    space_id = IDS.get(f"space_{space}")
    conn_id = IDS.get(f"conn_{space}")
    if space_id:
        post(
            "/agents/",
            {
                "name": name,
                "archetype": archetype,
                "scope": scope,
                "scope_id": space_id,
                "scope_name": space.title(),
                "monitor_type": mtype,
                "focus": focus,
                "frequency": freq,
                "connection_ids": [conn_id] if conn_id else [],
            },
            name,
        )

# ── 7. ENTERPRISE RELATIONSHIPS ────────────────────────────
print("\n--- Relationships ---")
# These are created via the API if the endpoint exists
for src_space, rel_type, tgt_space, desc in [
    ("marketing", "drives", "finance", "Marketing leads drive Finance revenue pipeline"),
    ("engineering", "impacts", "operations", "Engineering deployments impact Operations SLA"),
    (
        "finance",
        "correlates_with",
        "marketing",
        "Finance budget allocation correlates with Marketing spend",
    ),
    ("operations", "depends_on", "engineering", "Operations depends on Engineering infrastructure"),
]:
    src_id = IDS.get(f"space_{src_space}")
    tgt_id = IDS.get(f"space_{tgt_space}")
    if src_id and tgt_id:
        # Try the enterprise relationships endpoint
        try:
            r = CLIENT.post(
                "/enterprise/relationships",
                json={
                    "name": f"{src_space.title()} {rel_type} {tgt_space.title()}",
                    "description": desc,
                    "sources": [{"id": src_id, "type": "space"}],
                    "target_id": tgt_id,
                    "target_type": "space",
                    "relationship_type": rel_type,
                },
            )
            if r.status_code in (200, 201):
                print(f"  + {src_space} --[{rel_type}]--> {tgt_space}")
            else:
                print(f"  x Relationship ({r.status_code}): {r.text[:80]}")
        except Exception as e:
            print(f"  x Relationship error: {e}")

# ════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  NovaTech Demo Seed COMPLETE")
print("=" * 60)
print(f"\n  Spaces:      {len([k for k in IDS if k.startswith('space_')])}")
print(f"  Crews:       {len([k for k in IDS if k.startswith('crew_')])}")
print(f"  Connections: {len([k for k in IDS if k.startswith('conn_')])}")
print(f"  Events:      {len(EVENTS)}")
print(f"  Agents:      {len(AGENTS)}")
print(f"\nTest questions:")
print('  Strategy: "What are our OKRs for Q2?"')
print('  Data:     "What is our total revenue?"')
print('  Events:   "What market signals should we watch?"')
print('  Mixed:    "How much of our MRR OKR have we achieved?"')

CLIENT.close()
