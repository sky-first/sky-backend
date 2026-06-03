"""Tests for knowledge_context_loader — pins the AI rewire contract.

The loader is the single chokepoint where Metrics + Glossary become
visible to the AI engine. If this drifts, the chat answers stop
preferring Org-certified definitions — the exact W2 / governance gap
the Knowledge refactor closes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.glossary import GlossaryTerm
from src.models.metric import Metric
from src.schemas.metric import MetricCreate
from src.services.knowledge_context_loader import (
    load_knowledge_context_for_user,
    render_knowledge_for_prompt,
)
from src.services.metric_service import MetricService


@pytest.mark.asyncio
async def test_loader_returns_personal_metrics_for_owner(db_session: AsyncSession, test_user):
    user = test_user["user"]
    await MetricService(db_session).create(
        user, MetricCreate(name="My MRR", scope="personal", scope_id=user.id)
    )
    ctx = await load_knowledge_context_for_user(db_session, user)
    names = [m["name"] for m in ctx["metrics"]]
    assert "My MRR" in names


@pytest.mark.asyncio
async def test_loader_separates_preferred_org_certified_metrics(
    db_session: AsyncSession, test_user
):
    user = test_user["user"]
    user.role = "super_admin"
    db_session.add(user)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(
        user, MetricCreate(name="Personal Revenue", scope="personal", scope_id=user.id)
    )
    org_metric = await service.create(
        user, MetricCreate(name="Org Revenue", scope="org", scope_id=None)
    )
    # Mark the Org metric as certified so the loader surfaces it as preferred.
    org_metric.certified_by_user_id = user.id
    db_session.add(org_metric)
    await db_session.commit()

    ctx = await load_knowledge_context_for_user(db_session, user)
    preferred_names = [m["name"] for m in ctx["preferred_metrics"]]
    assert "Org Revenue" in preferred_names
    assert "Personal Revenue" not in preferred_names


@pytest.mark.asyncio
async def test_loader_skips_deprecated_metrics(db_session: AsyncSession, test_user):
    user = test_user["user"]
    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Old metric", scope="personal", scope_id=user.id)
    )
    m.status = "deprecated"
    db_session.add(m)
    await db_session.commit()

    ctx = await load_knowledge_context_for_user(db_session, user)
    names = [r["name"] for r in ctx["metrics"]]
    assert "Old metric" not in names


@pytest.mark.asyncio
async def test_loader_returns_org_glossary(db_session: AsyncSession, test_user):
    user = test_user["user"]
    term = GlossaryTerm(
        term="ARR",
        definition="Annual recurring revenue.",
        scope="org",
    )
    db_session.add(term)
    await db_session.commit()

    ctx = await load_knowledge_context_for_user(db_session, user)
    terms = [g["term"] for g in ctx["glossary"]]
    assert "ARR" in terms


@pytest.mark.asyncio
async def test_loader_includes_relationships(db_session: AsyncSession, test_user):
    """E2E proof — relationships flow into the AI prompt context.

    Closes the gap the user flagged: Knowledge + Metrics had been
    wired in, but enterprise relationships were not. An AI question
    that needs to join across data sources must see the relationship
    catalog, otherwise the answer can't reason about how a metric on
    BigQuery relates to a row in another connection.
    """
    from src.models.enterprise_relationship import EnterpriseRelationship

    user = test_user["user"]
    rel = EnterpriseRelationship(
        name="Customer ↔ Revenue",
        sources=[{"id": "customers.email", "type": "column"}],
        target_id="revenue.customer_email",
        target_type="column",
        relationship_type="depends_on",
        scope="org",
        ai_inferred=True,
        confidence=0.92,
        created_by=user.id,
    )
    db_session.add(rel)
    await db_session.commit()

    ctx = await load_knowledge_context_for_user(db_session, user)
    names = [r["name"] for r in ctx["relationships"]]
    assert "Customer ↔ Revenue" in names

    rendered = render_knowledge_for_prompt(ctx)
    assert "Customer ↔ Revenue" in rendered
    assert "Enterprise relationships" in rendered
    assert "AI-inferred" in rendered  # confidence tag rendered for AI rows


@pytest.mark.asyncio
async def test_render_for_prompt_emits_certified_tag(db_session: AsyncSession, test_user):
    user = test_user["user"]
    user.role = "super_admin"
    db_session.add(user)
    await db_session.flush()

    service = MetricService(db_session)
    org_metric = await service.create(
        user,
        MetricCreate(
            name="MRR",
            scope="org",
            scope_id=None,
            formula_description="Sum of active subscription value, monthly.",
        ),
    )
    org_metric.certified_by_user_id = user.id
    db_session.add(org_metric)
    await db_session.commit()

    ctx = await load_knowledge_context_for_user(db_session, user)
    rendered = render_knowledge_for_prompt(ctx)
    assert "MRR" in rendered
    assert "ORG-CERTIFIED" in rendered
