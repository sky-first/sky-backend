#!/usr/bin/env python3
"""Seed one of each Knowledge artefact for a target user, financial flavour.

Used by the AI E2E smoke proof — guarantees that
``load_knowledge_context_for_user`` returns a populated context so we
can show the AI prompt actually carries Metrics + Glossary +
Relationships alongside the user's BigQuery connections.

Idempotent: re-running won't create duplicates.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.enterprise_relationship import EnterpriseRelationship  # noqa: E402
from src.models.glossary import GlossaryTerm  # noqa: E402
from src.models.metric import Metric  # noqa: E402
from src.models.user import User  # noqa: E402


async def main() -> int:
    target_email = os.getenv(
        "SEED_USER_EMAIL", "lucas.ventura@skyfirstlabs.com"
    )
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == target_email))
        ).scalar_one_or_none()
        if user is None:
            print(f"[FAIL] user {target_email} not found")
            return 2

        # Metric — Org-certified Monthly Revenue.
        existing_metric = (
            await db.execute(
                select(Metric).where(
                    Metric.name == "Monthly Revenue",
                    Metric.scope == "org",
                    Metric.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_metric is None:
            metric = Metric(
                name="Monthly Revenue",
                slug="monthly-revenue",
                description="Total invoiced revenue per calendar month.",
                scope="org",
                scope_id=None,
                status="active",
                formula_text="SUM(invoices.total) GROUP BY DATE_TRUNC('month', invoices.issued_at)",
                formula_description=(
                    "Sum of invoice totals, grouped by calendar month "
                    "(matches Finance close ledger)."
                ),
                formula_language="sql",
                aggregation="sum",
                unit="USD",
                time_grain="month",
                tags=["financial", "revenue", "kpi"],
                owner_user_id=user.id,
                created_by_user_id=user.id,
                certified_by_user_id=user.id,
            )
            db.add(metric)
            await db.flush()
            print(f"[seed] metric created : {metric.id}")
        else:
            print(f"[seed] metric exists  : {existing_metric.id}")

        # Glossary — MRR.
        existing_term = (
            await db.execute(
                select(GlossaryTerm).where(
                    GlossaryTerm.term == "MRR",
                    GlossaryTerm.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_term is None:
            term = GlossaryTerm(
                term="MRR",
                definition=(
                    "Monthly Recurring Revenue — normalised value of all "
                    "active subscription contracts at the end of the month. "
                    "Excludes one-off charges."
                ),
                aliases=["Monthly Recurring Revenue"],
                scope="org",
                status="approved",
                created_by_user_id=user.id,
                certified_by_user_id=user.id,
            )
            db.add(term)
            await db.flush()
            print(f"[seed] glossary created: {term.id}")
        else:
            print(f"[seed] glossary exists : {existing_term.id}")

        # Relationship — customer.email ↔ revenue.customer_email,
        # AI-inferred with high confidence so the UI banner picks it up.
        existing_rel = (
            await db.execute(
                select(EnterpriseRelationship).where(
                    EnterpriseRelationship.name == "Customer ↔ Revenue (BigQuery)"
                )
            )
        ).scalar_one_or_none()
        if existing_rel is None:
            rel = EnterpriseRelationship(
                name="Customer ↔ Revenue (BigQuery)",
                description=(
                    "Joins the financial revenue table on the customers "
                    "master via email — used by Monthly Revenue to roll up "
                    "by account."
                ),
                sources=[{"id": "customers.email", "type": "column"}],
                target_id="revenue.customer_email",
                target_type="column",
                relationship_type="depends_on",
                scope="org",
                ai_inferred=True,
                confidence=0.92,
                created_by=user.id,
            )
            db.add(rel)
            await db.flush()
            print(f"[seed] relationship created: {rel.id}")
        else:
            print(f"[seed] relationship exists : {existing_rel.id}")

        await db.commit()
        print("[done] financial knowledge seeded")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
