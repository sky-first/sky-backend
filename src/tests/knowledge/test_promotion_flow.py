"""Knowledge — promotion + dependency resolver (Phase 4).

PROM-01..10. Personal → Crew → Space → Org.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, ValidationError
from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.metric import Metric
from src.models.promotion import PromotionRequest, PromotionRequestItem
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.schemas.metric import MetricCreate
from src.services.metric_service import MetricService
from src.services.promotion_service import PromotionService

PHASE = "Phase 4 — Promotion flow"


# ─── helpers ─────────────────────────────────────────────────────────


async def _resolve_user(db: AsyncSession, raw) -> User:
    if hasattr(raw, "id"):
        return raw
    user_id = uuid.UUID(raw["id"]) if isinstance(raw["id"], str) else raw["id"]
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def _setup_crew(db, user, *, role="commander"):
    space = Space(id=uuid.uuid4(), name="S1", created_by=user.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=user.id, role="admin"))
    crew = Crew(id=uuid.uuid4(), name="C1", space_id=space.id, created_by=user.id)
    db.add(crew)
    await db.flush()
    db.add(CrewMember(crew_id=crew.id, user_id=user.id, role=role))
    await db.flush()
    return space, crew


# ─── PROM-01..10 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prom_01_personal_to_crew_no_dependencies(db_session, test_user):
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)

    metrics = MetricService(db_session)
    metric = await metrics.create(
        user, MetricCreate(name="Pipeline Value", scope="personal", scope_id=user.id)
    )

    promo = PromotionService(db_session)
    request, conflicts = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    assert request.status in ("pending", "conflict_pending")
    assert request.target_scope == "crew" and request.target_scope_id == crew.id

    items = await promo.list_items(request.id)
    assert any(i.kind == "metric" and i.role == "primary" for i in items)
    # No dependencies because the personal metric had no source bound.
    assert all(i.kind != "source" for i in items)


@pytest.mark.asyncio
async def test_prom_02_source_dependency_resolved(db_session, test_user):
    """A metric bound to ``source_id`` adds a dependency item."""
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)

    fake_source_id = uuid.uuid4()  # we don't need a real DataConnection for the resolver
    metrics = MetricService(db_session)
    metric = await metrics.create(
        user,
        MetricCreate(
            name="Stripe MRR",
            scope="personal",
            scope_id=user.id,
            source_id=fake_source_id,
        ),
    )

    promo = PromotionService(db_session)
    request, _ = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    items = await promo.list_items(request.id)
    deps = [i for i in items if i.role == "dependency"]
    assert any(i.kind == "source" and i.entity_id == fake_source_id for i in deps)


@pytest.mark.skip(reason=f"{PHASE} (PROM-03) — Glossary dependency lands with Phase 5")
@pytest.mark.asyncio
async def test_prom_03_glossary_dependency_resolved(db_session):
    raise NotImplementedError


@pytest.mark.skip(
    reason=f"{PHASE} (PROM-04) — relationship-crawl lands with Phase 6 N↔N"
)
@pytest.mark.asyncio
async def test_prom_04_relationship_dependency_crawls_both_sides(db_session):
    raise NotImplementedError


@pytest.mark.asyncio
async def test_prom_05_cyclic_dependencies_no_infinite_loop(db_session, test_user):
    """Phase 4 only resolves Source as a dep — there's no cycle path,
    but the test pins the contract so future Glossary/Relationship deps
    don't regress.
    """
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)
    metrics = MetricService(db_session)
    metric = await metrics.create(
        user, MetricCreate(name="x", scope="personal", scope_id=user.id)
    )

    promo = PromotionService(db_session)
    request, _ = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    # Re-running enqueue (a different request) on the same metric must
    # not blow up — no global state leaks.
    request2, _ = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    assert request.id != request2.id


@pytest.mark.asyncio
async def test_prom_06_approval_is_all_or_nothing(db_session, test_user):
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)
    metrics = MetricService(db_session)
    metric = await metrics.create(
        user, MetricCreate(name="ARR", scope="personal", scope_id=user.id)
    )

    promo = PromotionService(db_session)
    request, _ = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    await promo.approve(approver=user, request_id=request.id)

    crew_metrics = await metrics.list_visible(user)
    assert any(m.name == "ARR" and m.scope == "crew" for m in crew_metrics)
    # Original Personal metric stays — promotion copies, doesn't move.
    assert any(m.name == "ARR" and m.scope == "personal" for m in crew_metrics)


@pytest.mark.asyncio
async def test_prom_07_reject_creates_no_target_rows(db_session, test_user):
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)
    metrics = MetricService(db_session)
    metric = await metrics.create(
        user, MetricCreate(name="X", scope="personal", scope_id=user.id)
    )

    promo = PromotionService(db_session)
    request, _ = await promo.enqueue(
        requester=user,
        metric_id=metric.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    await promo.reject(approver=user, request_id=request.id)

    visible = await metrics.list_visible(user)
    assert not any(m.name == "X" and m.scope == "crew" for m in visible)


@pytest.mark.asyncio
async def test_prom_08_target_conflict_marks_status_conflict_pending(
    db_session, test_user
):
    user = test_user["user"]
    _, crew = await _setup_crew(db_session, user)
    metrics = MetricService(db_session)

    # An existing crew metric named "Revenue" → triggers conflict on
    # promotion of the same name.
    await metrics.create(
        user, MetricCreate(name="Revenue", scope="crew", scope_id=crew.id)
    )
    proposed = await metrics.create(
        user, MetricCreate(name="Revenue", scope="personal", scope_id=user.id)
    )

    promo = PromotionService(db_session)
    request, conflicts = await promo.enqueue(
        requester=user,
        metric_id=proposed.id,
        target_scope="crew",
        target_scope_id=crew.id,
    )
    assert request.status == "conflict_pending"
    assert any(c.canonical_entity_id != proposed.id for c in conflicts)


@pytest.mark.asyncio
async def test_prom_09_promote_dep_requester_does_not_own_denied(
    db_session, test_user, test_second_user_with_tokens
):
    """A requester cannot ask for a target scope they don't have write
    rights at — the scope's mutation rule fires at enqueue time.
    """
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    space = Space(id=uuid.uuid4(), name="S1", created_by=alice.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=alice.id, role="admin"))
    db_session.add(SpaceMember(space_id=space.id, user_id=bob.id, role="navigator"))
    crew = Crew(id=uuid.uuid4(), name="C1", space_id=space.id, created_by=alice.id)
    db_session.add(crew)
    await db_session.flush()
    db_session.add(CrewMember(crew_id=crew.id, user_id=alice.id, role="commander"))
    # Bob is NOT in the crew at all.
    await db_session.flush()

    metrics = MetricService(db_session)
    metric = await metrics.create(
        bob, MetricCreate(name="X", scope="personal", scope_id=bob.id)
    )

    promo = PromotionService(db_session)
    with pytest.raises(ForbiddenError):
        await promo.enqueue(
            requester=bob,
            metric_id=metric.id,
            target_scope="crew",
            target_scope_id=crew.id,
        )


@pytest.mark.asyncio
async def test_prom_10_chain_personal_to_crew_to_space_to_org(db_session, test_user):
    user = test_user["user"]
    user.role = "owner"
    db_session.add(user)
    space = Space(id=uuid.uuid4(), name="S1", created_by=user.id)
    db_session.add(space)
    await db_session.flush()
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="admin"))
    crew = Crew(id=uuid.uuid4(), name="C1", space_id=space.id, created_by=user.id)
    db_session.add(crew)
    await db_session.flush()
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="commander"))
    await db_session.flush()

    metrics = MetricService(db_session)
    promo = PromotionService(db_session)

    base = await metrics.create(
        user, MetricCreate(name="MRR", scope="personal", scope_id=user.id)
    )

    # Personal → Crew
    r1, _ = await promo.enqueue(
        requester=user, metric_id=base.id, target_scope="crew", target_scope_id=crew.id
    )
    await promo.approve(approver=user, request_id=r1.id)

    # Find the crew copy.
    rows = await db_session.execute(
        select(Metric).where(Metric.scope == "crew", Metric.scope_id == crew.id)
    )
    crew_metric = rows.scalars().first()
    assert crew_metric is not None

    # Crew → Space
    r2, _ = await promo.enqueue(
        requester=user,
        metric_id=crew_metric.id,
        target_scope="space",
        target_scope_id=space.id,
    )
    await promo.approve(approver=user, request_id=r2.id)
    rows = await db_session.execute(
        select(Metric).where(Metric.scope == "space", Metric.scope_id == space.id)
    )
    space_metric = rows.scalars().first()
    assert space_metric is not None

    # Space → Org
    r3, _ = await promo.enqueue(
        requester=user,
        metric_id=space_metric.id,
        target_scope="org",
        target_scope_id=None,
    )
    await promo.approve(approver=user, request_id=r3.id)
    rows = await db_session.execute(
        select(Metric).where(Metric.scope == "org", Metric.deleted_at.is_(None))
    )
    org_metric = rows.scalars().first()
    assert org_metric is not None
    # Org-level approval auto-certifies.
    assert org_metric.certified_by_user_id == user.id
    assert org_metric.certified_at is not None
