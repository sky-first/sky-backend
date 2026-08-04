#!/usr/bin/env python3
"""Seed 3 demo findings into Pulse — wired to the real NovaTech demo data.

Creates three personal-scope agents owned by the demo owner user, each with
one finding that references actual columns from the `demo_novatech` schema
(populated by `seed_demo_tables.sql`).

The findings are designed to look like a real autonomous run: each carries
evidence, reasoning, recommendation, confidence, and a small `rows` payload
the frontend Insight Cockpit can chart.

Run after:
  • migrations are applied
  • seed_demo_tables.sql ran (the `demo_novatech` schema exists)
  • seed-rbac-demo-users.py and/or seed_demo_connections.py ran (owner user
    + at least one DataConnection row exist)

Idempotent — on every run we drop the seeded agents (and their findings via
ON DELETE CASCADE) before recreating them, so changes to copy/numbers here
flow into the local DB without manual cleanup. Recognized by their
deterministic UUIDs — see `_AGENT_IDS` below.

Usage:
  source .env.local && python scripts/seed_demo_findings.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not os.environ.get("DATABASE_URL"):
    print("Set DATABASE_URL first (source .env.local).", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import select  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.agent import Agent, AgentExecution, AgentFinding  # noqa: E402
from src.models.connection import DataConnection  # noqa: E402
from src.models.user import User  # noqa: E402

# Deterministic IDs so re-running the script reuses the same rows
# (the script also deletes by these IDs upfront, so this is belt-and-braces).
_AGENT_IDS = {
    "revenue_sentinel": uuid.UUID("a0000000-0000-4000-8000-000000000001"),
    "customer_health": uuid.UUID("a0000000-0000-4000-8000-000000000002"),
    "concentration": uuid.UUID("a0000000-0000-4000-8000-000000000003"),
}

# Owner candidates — try the SSO real user first, then the RBAC demo owner.
_OWNER_EMAILS = ("lucas.ventura@skyfirstlabs.com", "rbac.owner@example.com")


async def _resolve_owner(db) -> User:
    for email in _OWNER_EMAILS:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if user:
            return user
    raise SystemExit(
        "No demo owner user found. Run seed-rbac-demo-users.py first "
        "(creates rbac.owner@example.com) or sign in once with the real SSO "
        "account so a User row exists for lucas.ventura@skyfirstlabs.com."
    )


async def _resolve_demo_connection(db) -> Optional[DataConnection]:
    """Pick any demo connection so findings link to a real row.

    Findings still render fine without one — connection_name is what the
    frontend shows — but we wire connection_id when available so deep-link
    flows (open connection from finding card) work too.
    """
    res = await db.execute(
        select(DataConnection).where(
            DataConnection.name.like("Demo —%"),
            DataConnection.deleted_at.is_(None),
        )
    )
    return res.scalars().first()


def _agent_row(
    agent_id: uuid.UUID,
    name: str,
    archetype: str,
    focus: str,
    owner: User,
    connection_id: Optional[uuid.UUID],
) -> Agent:
    now = datetime.now(timezone.utc)
    return Agent(
        id=agent_id,
        name=name,
        archetype=archetype,
        scope="personal",
        scope_id=str(owner.id),
        scope_name=owner.name or owner.email,
        status="active",
        monitor_type="question",
        focus=focus,
        frequency="daily",
        depth="standard",
        connection_ids=[connection_id] if connection_id else [],
        last_execution_at=now - timedelta(hours=4),
        next_execution_at=now + timedelta(hours=20),
        executions_this_month=12,
        cycles_consumed=36,
        created_by=owner.id,
    )


def _execution_row(
    agent_id: uuid.UUID,
    answer: str,
    sql: str,
) -> AgentExecution:
    finished = datetime.now(timezone.utc) - timedelta(hours=4)
    return AgentExecution(
        id=uuid.uuid4(),
        agent_id=agent_id,
        status="completed",
        cycles_consumed=3,
        findings_count=1,
        answer=answer,
        sql_executed=sql,
        started_at=finished - timedelta(seconds=42),
        finished_at=finished,
        duration_ms=42000,
    )


async def _seed(db) -> None:
    owner = await _resolve_owner(db)
    print(f"  owner: {owner.email}")

    conn = await _resolve_demo_connection(db)
    conn_id = conn.id if conn else None
    conn_name = conn.name if conn else "Demo — Finance"
    print(f"  connection: {conn_name} ({'wired' if conn_id else 'fallback name only'})")

    # 1. Drop existing seeded agents (cascades to findings + executions).
    for aid in _AGENT_IDS.values():
        existing = await db.get(Agent, aid)
        if existing:
            await db.delete(existing)
    await db.flush()

    # 2. Recreate agents.
    revenue_agent = _agent_row(
        _AGENT_IDS["revenue_sentinel"],
        "NovaTech Revenue Sentinel",
        "financial_analyst",
        "Watch monthly subscription revenue across NovaTech and surface "
        "any sustained dip in MRR or net profit.",
        owner,
        conn_id,
    )
    health_agent = _agent_row(
        _AGENT_IDS["customer_health"],
        "Customer Health Watch",
        "growth_intelligence",
        "Identify enterprise customers with health_score above 90 whose "
        "contracts renew in the next 90 days — flag expansion windows.",
        owner,
        conn_id,
    )
    concentration_agent = _agent_row(
        _AGENT_IDS["concentration"],
        "Concentration Risk Monitor",
        "operations_monitor",
        "Track MRR distribution across the customer book and warn when "
        "the top accounts cross a concentration threshold.",
        owner,
        conn_id,
    )
    db.add_all([revenue_agent, health_agent, concentration_agent])
    await db.flush()

    # 3. One execution + one finding per agent.
    # ── Risk: Q4 subscription revenue dip ────────────────────────────────
    revenue_sql = (
        "SELECT month, year, revenue\n"
        "FROM demo_novatech.revenue_monthly\n"
        "WHERE revenue_type = 'subscription'\n"
        "ORDER BY year, month;"
    )
    revenue_exec = _execution_row(
        revenue_agent.id,
        "Subscription revenue declined 12.8% across Q4 2025 "
        "(Sep $860k → Dec $750k) before recovering in Q1 2026.",
        revenue_sql,
    )
    db.add(revenue_exec)
    await db.flush()

    revenue_finding = AgentFinding(
        agent_id=revenue_agent.id,
        execution_id=revenue_exec.id,
        type="risk",
        severity="high",
        title="Q4 subscription revenue dipped 12.8% — recovery in Q1 was full but unmodelled",
        description=(
            "Subscription revenue fell three months in a row in Q4 2025: "
            "$860k (Sep) → $810k (Oct) → $780k (Nov) → $750k (Dec). "
            "That is a 12.8% drawdown on the largest revenue line, large "
            "enough to materially shift trailing-twelve-month growth. "
            "Q1 2026 fully recovered ($830k → $890k → $950k), so the dip "
            "looks seasonal, but no forecasting artefact in the workspace "
            "models it — meaning a Q4 plan made today would over-shoot."
        ),
        confidence=0.86,
        query="demo-seed:revenue-q4-dip",
        evidence=(
            "demo_novatech.revenue_monthly, revenue_type='subscription':\n"
            "  2025-09 revenue=860000\n"
            "  2025-10 revenue=810000  (-5.8%)\n"
            "  2025-11 revenue=780000  (-3.7%)\n"
            "  2025-12 revenue=750000  (-3.8%)\n"
            "  2026-01 revenue=830000  (+10.7%)\n"
            "  2026-02 revenue=890000  (+7.2%)\n"
            "  2026-03 revenue=950000  (+6.7%)"
        ),
        reasoning=(
            "1. Selected revenue_monthly because the agent's focus is "
            "monthly subscription MRR.\n"
            "2. Filtered revenue_type='subscription' to isolate the line "
            "that dominates total revenue.\n"
            "3. Detected three consecutive month-over-month declines "
            "(-5.8%, -3.7%, -3.8%), exceeding the 5% sustained-dip "
            "threshold the archetype watches for.\n"
            "4. Verified Q1 2026 reverted to growth, classifying the "
            "pattern as seasonal rather than structural.\n"
            "5. Cross-checked services revenue — the same Q4 dip shows up "
            "($155k Sep → $100k Dec), confirming the seasonality is "
            "company-wide, not channel-specific."
        ),
        recommendation=(
            "Add a Q4-seasonality factor to the revenue forecast so plans "
            "built in Q3 do not over-promise December. A 12.8% drawdown "
            "from peak is a defensible default."
        ),
        data_sources=[
            "demo_novatech.revenue_monthly",
            "demo_novatech.revenue_monthly.revenue",
            "demo_novatech.revenue_monthly.revenue_type",
        ],
        connection_id=conn_id,
        connection_name=conn_name,
        rows={
            "columns": ["period", "subscription_revenue"],
            "data": [
                ["2025-09", 860000],
                ["2025-10", 810000],
                ["2025-11", 780000],
                ["2025-12", 750000],
                ["2026-01", 830000],
                ["2026-02", 890000],
                ["2026-03", 950000],
            ],
            "truncated": False,
        },
    )

    # ── Opportunity: enterprise expansion candidates ─────────────────────
    health_sql = (
        "SELECT name, segment, mrr, health_score, contract_end\n"
        "FROM demo_novatech.customers\n"
        "WHERE segment = 'enterprise'\n"
        "  AND health_score >= 90\n"
        "  AND contract_end <= CURRENT_DATE + INTERVAL '90 days'\n"
        "ORDER BY mrr DESC;"
    )
    health_exec = _execution_row(
        health_agent.id,
        "Three enterprise accounts (Acme, BluePeak, RiverBank) clear the "
        "expansion threshold and renew inside 90 days.",
        health_sql,
    )
    db.add(health_exec)
    await db.flush()

    health_finding = AgentFinding(
        agent_id=health_agent.id,
        execution_id=health_exec.id,
        type="opportunity",
        severity="medium",
        title="3 enterprise accounts ready for expansion — combined $141k MRR up for renewal",
        description=(
            "Three enterprise customers carry a health score of 90 or "
            "higher AND have contracts that renew inside the next 90 days. "
            "Combined they represent $141k MRR — a $1.69M annualised line. "
            "Health-score ≥90 historically converts to expansion at "
            "roughly 60% in this book, so the realistic upside is "
            "$70k–$90k incremental MRR if the renewals are paired with an "
            "expansion conversation."
        ),
        confidence=0.78,
        query="demo-seed:enterprise-expansion-window",
        evidence=(
            "demo_novatech.customers, filtered segment='enterprise' AND "
            "health_score>=90 AND contract_end<=now+90d:\n"
            "  Acme Corp           — health 92, MRR $45k, renews 2026-01-15\n"
            "  BluePeak Financial  — health 95, MRR $41k, renews 2026-06-01\n"
            "  RiverBank Capital   — health 60, MRR $55k, renews 2025-06-01 (excluded — health below threshold)\n"
            "  KnightBridge Capital — health 88, MRR $50k, renews 2026-01-15 (excluded — health below threshold)\n"
            "  Atlas Pharma        — health 80, MRR $48k, renews 2025-09-01 (excluded — health below threshold)"
        ),
        reasoning=(
            "1. Joined customers on the standing health/segment filters "
            "the archetype monitors for.\n"
            "2. Added the renewal window: contract_end within 90 days "
            "from today.\n"
            "3. Three rows cleared all three filters; combined MRR sums "
            "to $141k.\n"
            "4. Cross-referenced last expansion conversion rate "
            "(~60% for health ≥90) to size the realistic upside."
        ),
        recommendation=(
            "Schedule QBR + expansion conversations for Acme, BluePeak "
            "and KnightBridge in the next 30 days. Pair each with a "
            "platform-tier upgrade proposal and a multi-year discount "
            "anchor to capture the renewal-plus-expansion in one cycle."
        ),
        data_sources=[
            "demo_novatech.customers",
            "demo_novatech.customers.health_score",
            "demo_novatech.customers.mrr",
            "demo_novatech.customers.contract_end",
        ],
        connection_id=conn_id,
        connection_name=conn_name,
        rows={
            "columns": ["customer", "mrr", "health_score", "contract_end"],
            "data": [
                ["Acme Corp", 45000, 92, "2026-01-15"],
                ["BluePeak Financial", 41000, 95, "2026-06-01"],
                ["KnightBridge Capital", 50000, 88, "2026-01-15"],
            ],
            "truncated": False,
        },
    )

    # ── Insight: customer concentration ──────────────────────────────────
    concentration_sql = (
        "SELECT name, segment, mrr,\n"
        "       mrr / SUM(mrr) OVER () AS share\n"
        "FROM demo_novatech.customers\n"
        "ORDER BY mrr DESC\n"
        "LIMIT 5;"
    )
    concentration_exec = _execution_row(
        concentration_agent.id,
        "Top 5 customers concentrate 25.6% of total MRR; top 3 alone "
        "carry $167k of the $1.07M book.",
        concentration_sql,
    )
    db.add(concentration_exec)
    await db.flush()

    concentration_finding = AgentFinding(
        agent_id=concentration_agent.id,
        execution_id=concentration_exec.id,
        type="insight",
        severity="medium",
        title="Top 3 customers concentrate 15.6% of MRR — single-account churn risk worth watching",
        description=(
            "DeltaForce Defense ($60k), RiverBank Capital ($55k) and "
            "NorthStar Industries ($52k) together represent $167k of "
            "$1.07M MRR — 15.6% of total. Two of the three (RiverBank "
            "60, NorthStar 75) sit below the 80 health-score line, "
            "meaning a single-account churn would erase roughly five "
            "months of net new ARR at the current growth rate."
        ),
        confidence=0.81,
        query="demo-seed:customer-concentration",
        evidence=(
            "demo_novatech.customers, top 5 by MRR:\n"
            "  DeltaForce Defense    — $60k (5.6%) — health 70\n"
            "  RiverBank Capital     — $55k (5.2%) — health 60\n"
            "  NorthStar Industries  — $52k (4.9%) — health 75\n"
            "  KnightBridge Capital  — $50k (4.7%) — health 88\n"
            "  Atlas Pharma          — $48k (4.5%) — health 80\n"
            "  Total MRR (50 customers): $1,068,500"
        ),
        reasoning=(
            "1. Computed each customer's share of total MRR with a "
            "window function over the customers table.\n"
            "2. Top 3 share = 15.6%; top 5 share = 25.6% — both well "
            "above the 'healthy distribution' band the archetype uses "
            "(<10% top-3, <20% top-5).\n"
            "3. Layered health_score on top: of the top 3, two sit below "
            "80, which doubles the perceived risk.\n"
            "4. Sized the impact: net new ARR from the last 6 months of "
            "the company runs at ~$33k MRR/month, so RiverBank alone "
            "(if churned) would erase ≈ 5 months of growth."
        ),
        recommendation=(
            "Move RiverBank and NorthStar into a dedicated retention "
            "track this quarter — exec sponsor, weekly check-in, and an "
            "early renewal conversation. Treat their health scores as "
            "leading indicators, not lagging metrics."
        ),
        data_sources=[
            "demo_novatech.customers",
            "demo_novatech.customers.mrr",
            "demo_novatech.customers.health_score",
        ],
        connection_id=conn_id,
        connection_name=conn_name,
        rows={
            "columns": ["customer", "mrr", "share_pct", "health_score"],
            "data": [
                ["DeltaForce Defense", 60000, 5.6, 70],
                ["RiverBank Capital", 55000, 5.2, 60],
                ["NorthStar Industries", 52000, 4.9, 75],
                ["KnightBridge Capital", 50000, 4.7, 88],
                ["Atlas Pharma", 48000, 4.5, 80],
            ],
            "truncated": False,
        },
    )

    db.add_all([revenue_finding, health_finding, concentration_finding])
    await db.commit()

    print("  ✓ 3 demo agents + 3 findings seeded")
    print(f"     • {revenue_agent.name}      → 1 risk")
    print(f"     • {health_agent.name}            → 1 opportunity")
    print(f"     • {concentration_agent.name}    → 1 insight")


async def main() -> None:
    print("=== Seeding demo Pulse findings ===")
    async with AsyncSessionLocal() as db:
        await _seed(db)


if __name__ == "__main__":
    asyncio.run(main())
