#!/usr/bin/env python3
"""Seed demo metrics + glossary terms in the "Demo - Sky" Space.

Run after `seed_demo_connections.py`. The metric formulas reference the
demo connection schemas (crm/marketing/finance/web_analytics/product_usage)
so the Sky orchestrator + SQL specialist can resolve them via RAG.

Idempotent: re-running upserts by (space_id, slug).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not os.environ.get("DATABASE_URL"):
    print("Set DATABASE_URL first.", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402


async def _sessao():
    """A sessao sobre a base onde os dados de demonstracao vivem hoje.

    Mesma historia do `smoke_test_e2e.py`: escrito antes do modelo
    multi-cliente, olhava sempre para o `DATABASE_URL` — a base da
    plataforma. Semeava as metricas e o glossario num espaco `Demo` que
    la sobrou, enquanto as 5 ligacoes de demonstracao vivem na base do
    cliente `sandbox`.

    Nao dava erro. Encontrava o espaco antigo, dizia `refreshed` cinco
    vezes, e o teste a seguir perguntava pelas metricas no sitio certo e
    nao as encontrava.
    """
    slug = (os.environ.get("TENANT_SLUG") or "").strip()
    if not slug:
        return AsyncSessionLocal()

    sys.path.insert(0, str(Path(__file__).parent))
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from _ligacao_ao_tenant import url_do_tenant

    url = await url_do_tenant(slug)
    print(f"  cliente {slug!r}: base dedicada resolvida a partir do registo")
    motor = create_async_engine(url, pool_pre_ping=True)
    return async_sessionmaker(motor, expire_on_commit=False)()


from src.models.user import User  # noqa: E402
from src.models.space import Space  # noqa: E402
from src.models.metric import Metric  # noqa: E402
from src.models.glossary import GlossaryTerm  # noqa: E402
from src.models.connection import DataConnection  # noqa: E402

OWNER_EMAIL = "rbac.owner@example.com"
SPACE_NAME = "Demo - Sky"  # falls back to em-dash variant; we resolve by exact match

DEMO_METRICS = [
    {
        "slug": "mrr",
        "name": "MRR",
        "description": "Monthly Recurring Revenue from active subscriptions.",
        "formula_text": (
            "SELECT date_trunc('month', period_start) AS month, "
            "SUM(amount_eur) AS mrr "
            "FROM finance.subscriptions "
            "WHERE status = 'active' "
            "GROUP BY 1 ORDER BY 1"
        ),
        "formula_description": "Soma das subscrições activas por mês.",
        "formula_language": "sql",
        "source_table": "finance.subscriptions",
        "source_column": "amount_eur",
        "aggregation": "sum",
        "unit": "EUR",
        "time_grain": "month",
        "target_value": 50000,
        "threshold_warning": 40000,
        "threshold_critical": 30000,
        "tags": ["revenue", "north-star", "saas"],
    },
    {
        "slug": "arpu",
        "name": "ARPU",
        "description": "Average Revenue Per User over the trailing month.",
        "formula_text": (
            "SELECT (SUM(amount_eur) / NULLIF(COUNT(DISTINCT customer_id), 0)) AS arpu "
            "FROM finance.subscriptions "
            "WHERE status = 'active' AND period_start >= now() - interval '30 days'"
        ),
        "formula_language": "sql",
        "source_table": "finance.subscriptions",
        "aggregation": "avg",
        "unit": "EUR",
        "time_grain": "month",
        "target_value": 80,
        "threshold_warning": 60,
        "tags": ["revenue", "saas"],
    },
    {
        "slug": "cac",
        "name": "CAC",
        "description": "Customer Acquisition Cost — paid spend ÷ new customers.",
        "formula_text": (
            "SELECT (SUM(spend_eur) / NULLIF(COUNT(DISTINCT new_customer_id), 0)) AS cac "
            "FROM marketing.campaigns c "
            "JOIN crm.customers cu ON cu.acquisition_channel = c.channel "
            "WHERE cu.signup_date >= now() - interval '90 days'"
        ),
        "formula_language": "sql",
        "source_table": "marketing.campaigns",
        "aggregation": "avg",
        "unit": "EUR",
        "time_grain": "quarter",
        "target_value": 120,
        "threshold_warning": 180,
        "threshold_critical": 250,
        "tags": ["growth", "marketing"],
    },
    {
        "slug": "dau-mau",
        "name": "DAU/MAU",
        "description": "Stickiness — daily active users divided by monthly active users.",
        "formula_text": (
            "SELECT (COUNT(DISTINCT user_id) FILTER (WHERE event_date = current_date)::float / "
            "NULLIF(COUNT(DISTINCT user_id) FILTER "
            "(WHERE event_date >= current_date - interval '30 days'), 0)) AS dau_mau "
            "FROM product_usage.events"
        ),
        "formula_language": "sql",
        "source_table": "product_usage.events",
        "aggregation": "ratio",
        "unit": "%",
        "time_grain": "day",
        "target_value": 0.30,
        "threshold_warning": 0.20,
        "tags": ["engagement", "product"],
    },
    {
        "slug": "churn-rate",
        "name": "Churn Rate",
        "description": "Monthly customer churn — cancelled subs ÷ start-of-period subs.",
        "formula_text": (
            "SELECT (COUNT(*) FILTER (WHERE cancelled_at >= now() - interval '30 days')::float / "
            "NULLIF(COUNT(*) FILTER (WHERE period_start <= now() - interval '30 days'), 0)) "
            "AS churn_rate "
            "FROM finance.subscriptions"
        ),
        "formula_language": "sql",
        "source_table": "finance.subscriptions",
        "aggregation": "ratio",
        "unit": "%",
        "time_grain": "month",
        "target_value": 0.03,
        "threshold_warning": 0.05,
        "threshold_critical": 0.08,
        "tags": ["retention", "saas"],
    },
]

DEMO_GLOSSARY = [
    {
        "slug": "cohort",
        "term": "Cohort",
        "definition": (
            "Group of users sharing a common acquisition characteristic, "
            "typically the signup month. Cohort analysis tracks how each "
            "group's behaviour evolves over time and isolates the effect "
            "of the acquisition vintage from the calendar effect."
        ),
        "aliases": ["Cohort", "Coorte", "Acquisition cohort"],
        "related_metric_slugs": ["churn-rate", "ltv-implicit"],
    },
    {
        "slug": "gmv",
        "term": "GMV",
        "definition": (
            "Gross Merchandise Value — total transactional value passing "
            "through the platform before refunds, returns and platform fees. "
            "GMV is a top-line measure of marketplace activity but is "
            "not the same as revenue."
        ),
        "aliases": ["GMV", "Gross Merchandise Value", "Volume Bruto"],
        "related_metric_slugs": [],
    },
    {
        "slug": "ltv",
        "term": "LTV",
        "definition": (
            "Customer Lifetime Value — present value of the total gross "
            "profit a single customer is expected to generate before "
            "churning. A common simplification is ARPU * gross_margin / "
            "monthly_churn_rate."
        ),
        "aliases": ["LTV", "Customer Lifetime Value", "Valor de Vida do Cliente"],
        "related_metric_slugs": ["arpu", "churn-rate"],
    },
    {
        "slug": "payback-period",
        "term": "Payback Period",
        "definition": (
            "Time required for the gross-margin contribution from a "
            "newly-acquired customer to repay the cost of acquiring "
            "that customer. CAC / (ARPU * gross_margin), expressed in "
            "months. Investors look for payback < 12 months in B2B SaaS."
        ),
        "aliases": ["Payback Period", "Payback", "Periodo de Payback"],
        "related_metric_slugs": ["cac", "arpu"],
    },
    {
        "slug": "voluntary-vs-involuntary-churn",
        "term": "Voluntary vs Involuntary Churn",
        "definition": (
            "Voluntary churn = customer actively cancels (price, switching "
            "to a competitor, no longer needs the product). Involuntary "
            "churn = subscription lapses for non-intentional reasons "
            "(failed card charges, expired payment methods). The two "
            "demand different remediations: voluntary needs product/price "
            "fixes, involuntary needs payment retry logic."
        ),
        "aliases": [
            "Voluntary churn",
            "Involuntary churn",
            "Churn voluntario",
            "Churn involuntario",
        ],
        "related_metric_slugs": ["churn-rate"],
    },
]


async def upsert_metric(
    db: AsyncSession, owner: User, space: Space, source_id_by_table: dict, spec: dict
) -> Metric:
    res = await db.execute(
        select(Metric).where(
            Metric.scope == "space",
            Metric.scope_id == space.id,
            Metric.slug == spec["slug"],
        )
    )
    metric = res.scalar_one_or_none()

    source_id = None
    if spec.get("source_table"):
        schema_name = spec["source_table"].split(".")[0]
        source_id = source_id_by_table.get(schema_name)

    fields = {
        "name": spec["name"],
        "description": spec["description"],
        "scope": "space",
        "scope_id": space.id,
        "status": "active",
        "formula_text": spec.get("formula_text"),
        "formula_description": spec.get("formula_description"),
        "formula_language": spec.get("formula_language", "sql"),
        "source_id": source_id,
        "source_table": spec.get("source_table"),
        "source_column": spec.get("source_column"),
        "aggregation": spec.get("aggregation"),
        "unit": spec.get("unit"),
        "time_grain": spec.get("time_grain"),
        "target_value": spec.get("target_value"),
        "threshold_warning": spec.get("threshold_warning"),
        "threshold_critical": spec.get("threshold_critical"),
        "tags": spec.get("tags") or [],
        "owner_user_id": owner.id,
        "created_by_user_id": owner.id,
        "updated_by_user_id": owner.id,
    }

    if metric:
        for k, v in fields.items():
            setattr(metric, k, v)
        await db.flush()
        print(f"  metric {spec['slug']!r} (id={metric.id}) refreshed")
    else:
        metric = Metric(id=uuid.uuid4(), slug=spec["slug"], **fields)
        db.add(metric)
        await db.flush()
        print(f"  metric {spec['slug']!r} (id={metric.id}) created")
    return metric


async def upsert_glossary(
    db: AsyncSession, owner: User, space: Space, metric_id_by_slug: dict, spec: dict
) -> GlossaryTerm:
    res = await db.execute(
        select(GlossaryTerm).where(
            GlossaryTerm.scope == "space",
            GlossaryTerm.scope_id == space.id,
            GlossaryTerm.slug == spec["slug"],
        )
    )
    term = res.scalar_one_or_none()

    related_metric_ids = [
        str(metric_id_by_slug[s])
        for s in spec.get("related_metric_slugs", [])
        if s in metric_id_by_slug
    ]

    fields = {
        "term": spec["term"],
        "definition": spec["definition"],
        "scope": "space",
        "scope_id": space.id,
        "space_id": space.id,
        "status": "active",
        "aliases": spec.get("aliases") or [],
        "related_metric_ids": related_metric_ids,
        "related_source_ids": [],
        "owner_user_id": owner.id,
        "created_by_user_id": owner.id,
    }

    if term:
        for k, v in fields.items():
            setattr(term, k, v)
        await db.flush()
        print(f"  glossary {spec['slug']!r} (id={term.id}) refreshed")
    else:
        term = GlossaryTerm(id=uuid.uuid4(), slug=spec["slug"], **fields)
        db.add(term)
        await db.flush()
        print(f"  glossary {spec['slug']!r} (id={term.id}) created")
    return term


async def main() -> None:
    print("=" * 60)
    print("Seeding demo metrics + glossary in 'Demo - Sky' Space")
    print("=" * 60)
    async with await _sessao() as db:
        owner = (
            await db.execute(select(User).where(User.email == OWNER_EMAIL))
        ).scalar_one_or_none()
        if not owner:
            print(f"Owner {OWNER_EMAIL} not found — run seed_demo_connections.py first.")
            sys.exit(2)

        # Match either em-dash variant ("Demo — Sky") or hyphen ("Demo - Sky")
        spaces = (
            (await db.execute(select(Space).where(Space.created_by == owner.id))).scalars().all()
        )
        space = next(
            (s for s in spaces if s.name and s.name.startswith("Demo") and "Sky" in s.name),
            None,
        )
        if not space:
            print("'Demo' Space not found — run seed_demo_connections.py first.")
            sys.exit(3)
        print(f"  space {space.name!r} (id={space.id})")

        # Map schema name → connection_id so metric.source_id can FK to it
        conns = (
            (
                await db.execute(
                    select(DataConnection).where(
                        DataConnection.created_by == owner.id,
                        DataConnection.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        source_id_by_table = {}
        for c in conns:
            cfg = c.config or {}
            # config is encrypted dict; the seed sets schema name explicitly
            # but encryption hides it — so we fall back to mapping by name suffix
            n = (c.name or "").lower()
            if "sales" in n:
                source_id_by_table["crm"] = c.id
            elif "marketing" in n:
                source_id_by_table["marketing"] = c.id
            elif "finance" in n:
                source_id_by_table["finance"] = c.id
            elif "web" in n:
                source_id_by_table["web_analytics"] = c.id
            elif "product" in n:
                source_id_by_table["product_usage"] = c.id

        metric_id_by_slug = {}
        for spec in DEMO_METRICS:
            m = await upsert_metric(db, owner, space, source_id_by_table, spec)
            metric_id_by_slug[spec["slug"]] = m.id

        for spec in DEMO_GLOSSARY:
            await upsert_glossary(db, owner, space, metric_id_by_slug, spec)

        await db.commit()

    print("\nDone. 5 metrics + 5 glossary terms wired into the demo Space.")


if __name__ == "__main__":
    asyncio.run(main())
