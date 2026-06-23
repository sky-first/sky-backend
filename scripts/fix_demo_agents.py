#!/usr/bin/env python3
"""Fix all existing demo-space agents: correct connection_ids and focus questions.

Run this on any environment (local, staging, prod) after deploying the
_seed_demo_agents fix. It is fully idempotent — safe to re-run.

What it does:
  1. Finds all Spaces created by demo users (demo=True in their JWT claims,
     or identified by the demo connections bound to the space).
  2. For each Space, resolves the 5 demo connections by name
     (Demo — Sales, Demo — Finance, etc.).
  3. Updates every agent whose connection_ids or focus doesn't match the
     canonical seed definition.

Usage:
  python scripts/fix_demo_agents.py [--dry-run]

Env vars required (same as the backend):
  DATABASE_URL  (or POSTGRES_* vars)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT.parent / ".env", override=False)

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.config.settings import settings
from src.models.agent import Agent
from src.models.space import Space, SpaceConnection
from src.models.connection import DataConnection

# ── Canonical seed definition ────────────────────────────────────────────────
# Each entry mirrors _seed_demo_agents() exactly.
# "conn_labels" maps to connection names via the label→name heuristic.
SEED = [
    {
        "name": "Strategic Health Audit",
        "conn_labels": ["finance", "product"],
        "focus": (
            "Show a summary: (1) total MRR from active subscriptions "
            "grouped by plan type (starter, pro, enterprise), and "
            "(2) count of accounts by health risk_level (churn, risk, "
            "watch, healthy) from account_health. Return both results."
        ),
    },
    {
        "name": "Revenue Pulse",
        "conn_labels": ["finance", "sales"],
        "focus": (
            "What is the current total MRR from active subscriptions? "
            "Also show total open pipeline value grouped by stage "
            "(prospect, qualified, negotiation) and the win rate from "
            "closed deals."
        ),
    },
    {
        "name": "Customer Health Watch",
        "conn_labels": ["product", "sales"],
        "focus": (
            "Show all accounts with risk_level of churn or risk in "
            "account_health. Include their health score, seats used "
            "versus seats paid, and last login date. Also show accounts "
            "with no last_login_at."
        ),
    },
    {
        "name": "Operations Radar",
        "conn_labels": ["product"],
        "focus": (
            "Show accounts where seats_used divided by seats_paid is "
            "below 0.5 (underutilization). Also show accounts where "
            "last_login_at is NULL or older than 30 days. Include "
            "account_id, score, and risk_level for each."
        ),
    },
    {
        "name": "Pipeline Velocity Delta",
        "conn_labels": ["sales"],
        "focus": (
            "How many open deals (prospect, qualified, negotiation "
            "stages) are there and what is the total pipeline value "
            "per stage? Show average deal size and count by stage."
        ),
    },
    {
        "name": "Support Ticket Spike",
        "conn_labels": ["product"],
        "focus": (
            "From product_usage.feature_adoption, show average "
            "times_used_30d per feature_name and count of accounts "
            "where times_used_30d is below 50. Do not apply any date "
            "filter — times_used_30d is already a pre-computed 30-day "
            "metric. Rank features from least used to most used."
        ),
    },
    {
        "name": "Payment Failure Tracker",
        "conn_labels": ["finance"],
        "focus": (
            "Show all invoices with status overdue or sent. How many "
            "are there and what is the total amount unpaid? Show count "
            "and sum grouped by status."
        ),
    },
    {
        "name": "Sign-up Anomaly",
        "conn_labels": ["web", "marketing"],
        "focus": (
            "How many signup events occurred in the web analytics events "
            "table? Show counts by month and by UTM source from sessions. "
            "Also show total leads by source from the marketing leads table."
        ),
    },
    {
        "name": "Login Failure Watch",
        "conn_labels": ["web"],
        "focus": (
            "Show session volume by week from web_analytics.sessions "
            "(count of started_at per week) and average pages_viewed "
            "per session. Flag weeks where session count drops more "
            "than 20% compared to the previous week. Also show the "
            "top 3 pages by page_path from web_analytics.events."
        ),
    },
    {
        "name": "Campaign ROI Watch",
        "conn_labels": ["marketing"],
        "focus": (
            "Show all marketing campaigns with their budget, spend, and "
            "lead count. Which channels have the most leads? Group "
            "campaigns by channel and show total budget vs total spend "
            "per channel."
        ),
    },
]

DEMO_CONN_IDS = {
    "9d286808-16b9-4d1e-b716-66253369800c",
    "b08d67fa-4934-41f4-84a5-a08763251fe9",
    "a823520b-5f14-4162-af5a-b14e0228690f",
    "6ef81703-5b23-49ff-8de3-524f172d3ebb",
    "aa113174-2d2d-4d7a-862e-c687674064d3",
}


def _label(name: str) -> str | None:
    """Map a connection name to a domain label (same heuristic as _conns())."""
    n = (name or "").lower()
    if "sales" in n or "crm" in n:
        return "sales"
    if "finance" in n:
        return "finance"
    if "marketing" in n:
        return "marketing"
    if "web" in n or "analytics" in n:
        return "web"
    if "product" in n or "usage" in n:
        return "product"
    return None


async def fix_space(
    session: AsyncSession,
    space: Space,
    dry_run: bool,
) -> dict:
    """Fix agents for one demo Space. Returns a stats dict."""
    # Build label → UUID map for this space's connections.
    sc_q = await session.execute(
        select(SpaceConnection.connection_id).where(SpaceConnection.space_id == space.id)
    )
    conn_ids = list(sc_q.scalars().all())

    dc_q = await session.execute(
        select(DataConnection.id, DataConnection.name).where(DataConnection.id.in_(conn_ids))
    )
    conn_by_label: dict[str, UUID] = {}
    for cid, cname in dc_q.all():
        lbl = _label(cname)
        if lbl:
            conn_by_label[lbl] = cid

    if not conn_by_label:
        return {"space_id": str(space.id), "skipped": True, "reason": "no labeled connections"}

    # Load existing agents for this space.
    ag_q = await session.execute(
        select(Agent).where(Agent.scope == "space", Agent.scope_id == str(space.id))
    )
    agents_by_name: dict[str, Agent] = {a.name: a for a in ag_q.scalars().all()}

    updated = 0
    for seed in SEED:
        agent = agents_by_name.get(seed["name"])
        if not agent:
            continue

        # Resolve desired connection_ids for this seed entry.
        desired_conns = [conn_by_label[lbl] for lbl in seed["conn_labels"] if lbl in conn_by_label]
        if not desired_conns:
            # Fallback to first available — same as _conns() fallback.
            desired_conns = [next(iter(conn_by_label.values()))]

        current_conns = sorted(str(c) for c in (agent.connection_ids or []))
        desired_conns_sorted = sorted(str(c) for c in desired_conns)

        needs_update = current_conns != desired_conns_sorted or agent.focus != seed["focus"]

        if needs_update:
            if not dry_run:
                agent.connection_ids = desired_conns
                agent.focus = seed["focus"]
            updated += 1
            print(
                f"  {'[DRY]' if dry_run else '[FIX]'} {seed['name']}: "
                f"connections {current_conns} → {desired_conns_sorted}"
            )

    if not dry_run and updated:
        await session.flush()

    return {"space_id": str(space.id), "updated": updated, "skipped": False}


async def main(dry_run: bool) -> None:
    db_url = settings.DATABASE_URL

    engine = create_async_engine(db_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Find all spaces that have at least one demo connection bound.
        demo_sc_q = await session.execute(
            select(SpaceConnection.space_id)
            .where(SpaceConnection.connection_id.in_([UUID(i) for i in DEMO_CONN_IDS]))
            .distinct()
        )
        space_ids = list(demo_sc_q.scalars().all())
        print(f"Found {len(space_ids)} demo spaces.")

        total_updated = 0
        for space_id in space_ids:
            sp_q = await session.execute(select(Space).where(Space.id == space_id))
            space = sp_q.scalar_one_or_none()
            if not space:
                continue

            print(f"\nSpace {space.id} ({space.name}):")
            result = await fix_space(session, space, dry_run)
            if result.get("skipped"):
                print(f"  SKIPPED — {result.get('reason')}")
            else:
                n = result["updated"]
                total_updated += n
                if n == 0:
                    print("  Already correct — no changes needed.")

        if not dry_run:
            await session.commit()
            print(f"\n✅ Done. {total_updated} agents updated across {len(space_ids)} spaces.")
        else:
            print(f"\n[DRY RUN] {total_updated} agents would be updated.")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing."
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
