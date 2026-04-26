"""Knowledge — CRUD baseline for Metric + GlossaryTerm.

Phase 2. Basic create / read / update / delete + listing.
Wraps the ACL contract; CRUD without ACL would be a regression
hazard, so these are interleaved with visibility tests in CI.

Tests CRUD-01..08 are implemented against the Metric model that
landed in Phase 2. CRUD-09..12 cover the GlossaryTerm rebuild and
remain skipped until that schema is rewritten in Phase 4.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.schemas.metric import MetricCreate, MetricUpdate
from src.services.metric_service import MetricService

PHASE = "Phase 2 — CRUD baseline"


# ─── helpers ──────────────────────────────────────────────────────────────


async def _new_metric(service, user, name: str, scope: str = "personal", **overrides):
    payload = MetricCreate(
        name=name,
        scope=scope,
        scope_id=user.id if scope == "personal" else overrides.pop("scope_id", None),
        **overrides,
    )
    return await service.create(user, payload)


# ─── CRUD-01..08 — Metric ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crud_01_create_metric(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    metric = await _new_metric(service, user, "Monthly Recurring Revenue")
    assert metric.id is not None
    assert metric.name == "Monthly Recurring Revenue"
    assert metric.slug == "monthly-recurring-revenue"
    assert metric.scope == "personal"
    assert metric.scope_id == user.id
    assert metric.status == "draft"
    assert metric.owner_user_id == user.id
    assert metric.created_by_user_id == user.id


@pytest.mark.asyncio
async def test_crud_02_get_metric(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]
    created = await _new_metric(service, user, "Churn Rate")

    fetched = await service.get(user, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Churn Rate"


@pytest.mark.asyncio
async def test_crud_03_list_metrics_in_scope(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    await _new_metric(service, user, "Active Users")
    await _new_metric(service, user, "DAU/MAU Ratio")

    rows = await service.list_visible(user)
    names = sorted(m.name for m in rows)
    assert "Active Users" in names
    assert "DAU/MAU Ratio" in names


@pytest.mark.asyncio
async def test_crud_04_update_metric(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    m = await _new_metric(service, user, "Pipeline Value")
    updated = await service.update(
        user,
        m.id,
        MetricUpdate(name="Pipeline Value (USD)", description="Sum of open opportunities."),
    )
    assert updated.name == "Pipeline Value (USD)"
    assert updated.slug == "pipeline-value-usd"
    assert updated.description == "Sum of open opportunities."
    assert updated.updated_by_user_id == user.id


@pytest.mark.asyncio
async def test_crud_05_soft_delete_sets_deleted_at(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    m = await _new_metric(service, user, "Stale Metric")
    await service.delete(user, m.id)

    # Soft-deleted rows are excluded from `list_visible` and `get`.
    visible = await service.list_visible(user)
    assert all(row.id != m.id for row in visible)

    from src.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get(user, m.id)


@pytest.mark.asyncio
async def test_crud_06_slug_unique_per_scope(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    m1 = await _new_metric(service, user, "Revenue")
    m2 = await _new_metric(service, user, "Revenue")

    assert m1.slug == "revenue"
    assert m2.slug == "revenue-2"


@pytest.mark.asyncio
async def test_crud_07_tags_persisted(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    m = await _new_metric(
        service,
        user,
        "Net Revenue",
        tags=["pillar:growth", "owner:finance"],
    )
    fetched = await service.get(user, m.id)
    assert sorted(fetched.tags) == ["owner:finance", "pillar:growth"]


@pytest.mark.asyncio
async def test_crud_08_target_and_threshold_persisted(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    from datetime import date

    m = await _new_metric(
        service,
        user,
        "Customer NPS",
        target_value=Decimal("60"),
        target_date=date(2026, 12, 31),
        threshold_warning=Decimal("45"),
        threshold_critical=Decimal("30"),
    )
    fetched = await service.get(user, m.id)
    assert fetched.target_value == Decimal("60")
    assert fetched.threshold_warning == Decimal("45")
    assert fetched.threshold_critical == Decimal("30")
    assert fetched.target_date.isoformat() == "2026-12-31"


# ─── CRUD-09..11 — GlossaryTerm Phase 5 rebuild ──────────────────────


@pytest.mark.asyncio
async def test_crud_09_create_glossary_term(db_session, test_user):
    """The Phase 5 columns (scope/scope_id/slug/status) are populated
    directly via the model — pins the new schema contract."""
    from src.models.glossary import GlossaryTerm
    user = test_user["user"]
    term = GlossaryTerm(
        term="ARR",
        slug="arr",
        scope="personal",
        scope_id=user.id,
        definition="Annual recurring revenue.",
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    db_session.add(term)
    await db_session.commit()
    await db_session.refresh(term)

    assert term.id is not None
    assert term.scope == "personal"
    assert term.scope_id == user.id
    assert term.slug == "arr"
    assert term.status == "active"  # server_default


@pytest.mark.asyncio
async def test_crud_10_glossary_aliases_persisted(db_session, test_user):
    from src.models.glossary import GlossaryTerm
    user = test_user["user"]
    term = GlossaryTerm(
        term="MRR",
        slug="mrr",
        scope="personal",
        scope_id=user.id,
        definition="Monthly recurring revenue.",
        aliases=["Monthly RR", "Recurring Monthly Rev"],
        owner_user_id=user.id,
    )
    db_session.add(term)
    await db_session.commit()
    await db_session.refresh(term)

    assert sorted(term.aliases) == ["Monthly RR", "Recurring Monthly Rev"]


@pytest.mark.asyncio
async def test_crud_11_glossary_relates_to_metric_and_source(db_session, test_user):
    from src.models.glossary import GlossaryTerm

    user = test_user["user"]
    metric_id = uuid.uuid4()
    source_id = uuid.uuid4()
    term = GlossaryTerm(
        term="GMV",
        slug="gmv",
        scope="personal",
        scope_id=user.id,
        definition="Gross merchandise value.",
        related_metric_ids=[str(metric_id)],
        related_source_ids=[str(source_id)],
        owner_user_id=user.id,
    )
    db_session.add(term)
    await db_session.commit()
    await db_session.refresh(term)

    assert term.related_metric_ids == [str(metric_id)]
    assert term.related_source_ids == [str(source_id)]


@pytest.mark.asyncio
async def test_crud_12_metric_stores_both_formula_text_and_description(db_session, test_user):
    service = MetricService(db_session)
    user = test_user["user"]

    m = await _new_metric(
        service,
        user,
        "Average Order Value",
        formula_description="Average revenue per paid order.",
        formula_text="SELECT AVG(amount) FROM orders WHERE status='paid'",
        formula_language="sql",
    )
    fetched = await service.get(user, m.id)
    assert fetched.formula_text and "orders" in fetched.formula_text
    assert fetched.formula_description == "Average revenue per paid order."
    assert fetched.formula_language == "sql"
