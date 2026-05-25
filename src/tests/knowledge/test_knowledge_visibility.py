"""Knowledge — visibility / ACL contract.

Phase 2. Pins the read-side rules from KNOWLEDGE_REFACTOR.md §5.1
(ACL-01 through ACL-10).

ACL-01..08 + ACL-10 are implemented against the Metric service that
landed in Phase 2. ACL-09 (embedding ACL parity with the AI service)
remains skipped — it lands when the AI-side
``list_authorized_embedding_ids`` rewires onto the new scope/scope_id
columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.metric import Metric
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.schemas.metric import MetricCreate
from src.services.metric_service import MetricService

PHASE = "Phase 2 — Knowledge tables + ACL"


# ─── Fixture helpers — multi-user, multi-crew, multi-space scaffolding ──


async def _resolve_user(db: AsyncSession, raw) -> User:
    """The conftest mixes return shapes — `test_user` returns the User
    object under ``["user"]`` while `test_second_user_with_tokens`
    returns a dict with ``id/email/role``. Normalize either to the ORM
    object so the visibility tests don't have to care.
    """
    if hasattr(raw, "id"):
        return raw
    from sqlalchemy import select

    user_id = uuid.UUID(raw["id"]) if isinstance(raw["id"], str) else raw["id"]
    stmt = select(User).where(User.id == user_id)
    return (await db.execute(stmt)).scalar_one()


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        name=email.split("@")[0],
        password_hash=get_password_hash("x"),
        role="admin",
    )
    db.add(user)
    await db.flush()
    return user


async def _make_space(db: AsyncSession, name: str, owner: User) -> Space:
    space = Space(id=uuid.uuid4(), name=name, created_by=owner.id)
    db.add(space)
    await db.flush()
    return space


async def _add_to_space(
    db: AsyncSession, user: User, space: Space, role: str = "owner"
) -> None:
    """Default role is ``owner`` so visibility tests that seed
    space-scoped metrics can pass the Phase 3 mutation gate.
    """
    db.add(SpaceMember(space_id=space.id, user_id=user.id, role=role))
    await db.flush()


async def _make_crew(db: AsyncSession, name: str, space: Space, owner: User) -> Crew:
    crew = Crew(id=uuid.uuid4(), name=name, space_id=space.id, created_by=owner.id)
    db.add(crew)
    await db.flush()
    return crew


async def _add_to_crew(db: AsyncSession, user: User, crew: Crew, role: str = "editor") -> None:
    """Default role is ``editor`` so tests can both READ (visibility)
    and WRITE (the Phase 3 mutation gate accepts editor). Explicit
    ``viewer`` is what tests pass when they want to assert the deny path.
    """
    db.add(CrewMember(crew_id=crew.id, user_id=user.id, role=role))
    await db.flush()


async def _seed_metric(
    db: AsyncSession, scope: str, scope_id, *, name: str, owner: User
) -> Metric:
    """Insert directly to bypass the service-level personal-only guard.

    The service layer locks personal scope to the caller's id, so for
    the ACL tests where User A creates a metric for User B / Crew /
    Space we go through the model directly. Visibility logic is what
    we're testing — not the create path.
    """
    service = MetricService(db)
    payload = MetricCreate(
        name=name,
        scope=scope,
        scope_id=scope_id if scope != "org" else None,
    )
    if scope == "personal":
        # Personal must be authored by the matching user.
        metric = await service.create(owner, payload)
        return metric

    # For crew/space/org we can call the service with any user that
    # passes its (scope ≠ personal) gate (Phase 2 has no further
    # mutation gate; Phase 3 will plug platform-role grants).
    metric = await service.create(owner, payload)
    return metric


# ─── ACL tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acl_01_owner_sees_their_personal_metric(db_session, test_user):
    """Personal scope is the user's sandbox — they always see their own."""
    user = test_user["user"]
    service = MetricService(db_session)
    await service.create(
        user, MetricCreate(name="My ARR", scope="personal", scope_id=user.id)
    )
    visible = await service.list_visible(user)
    assert any(m.name == "My ARR" for m in visible)


@pytest.mark.asyncio
async def test_acl_02_user_does_not_see_another_users_personal_metric(
    db_session, test_user, test_second_user_with_tokens
):
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    service = MetricService(db_session)

    await service.create(
        alice, MetricCreate(name="Alice's pipeline", scope="personal", scope_id=alice.id)
    )

    bobs_visible = await service.list_visible(bob)
    names = {m.name for m in bobs_visible}
    assert "Alice's pipeline" not in names


@pytest.mark.asyncio
async def test_acl_03_crew_member_sees_crew_metric(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space)
    crew = await _make_crew(db_session, "C1", space, user)
    await _add_to_crew(db_session, user, crew)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(
        user, MetricCreate(name="C1 metric", scope="crew", scope_id=crew.id)
    )

    visible = await service.list_visible(user)
    assert any(m.name == "C1 metric" for m in visible)


@pytest.mark.asyncio
async def test_acl_04_crew_member_does_not_see_sibling_crew_metric(
    db_session, test_user, test_second_user_with_tokens
):
    """Headline test: Alice in C1, Bob in C2; both in S1.
    Alice MUST NOT see C2's crew-scoped metric.
    """
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    space = await _make_space(db_session, "S1", alice)
    await _add_to_space(db_session, alice, space)
    await _add_to_space(db_session, bob, space)

    c1 = await _make_crew(db_session, "C1", space, alice)
    await _add_to_crew(db_session, alice, c1)

    c2 = await _make_crew(db_session, "C2", space, bob)
    await _add_to_crew(db_session, bob, c2)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(bob, MetricCreate(name="C2 secret", scope="crew", scope_id=c2.id))

    alice_visible = await service.list_visible(alice)
    names = {m.name for m in alice_visible}
    assert "C2 secret" not in names


@pytest.mark.asyncio
async def test_acl_05_crew_member_sees_parent_space_metric(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space)
    crew = await _make_crew(db_session, "C1", space, user)
    await _add_to_crew(db_session, user, crew)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(
        user, MetricCreate(name="S1 metric", scope="space", scope_id=space.id)
    )

    visible = await service.list_visible(user)
    assert any(m.name == "S1 metric" for m in visible)


@pytest.mark.asyncio
async def test_acl_06_user_in_one_space_does_not_see_other_space_metrics(
    db_session, test_user, test_second_user_with_tokens
):
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    s1 = await _make_space(db_session, "S1", alice)
    await _add_to_space(db_session, alice, s1)
    s2 = await _make_space(db_session, "S2", bob)
    await _add_to_space(db_session, bob, s2)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(bob, MetricCreate(name="S2 metric", scope="space", scope_id=s2.id))

    visible = await service.list_visible(alice)
    names = {m.name for m in visible}
    assert "S2 metric" not in names


@pytest.mark.asyncio
async def test_acl_07_all_authenticated_users_see_org_metrics(
    db_session, test_user, test_second_user_with_tokens
):
    alice = test_user["user"]
    # Org create needs Owner role — bump alice for the duration of
    # this test (Phase 3 mutation gate).
    alice.role = "owner"
    db_session.add(alice)
    await db_session.flush()

    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])

    service = MetricService(db_session)
    await service.create(
        alice, MetricCreate(name="Org-canonical MRR", scope="org", scope_id=None)
    )

    for u in (alice, bob):
        visible = await service.list_visible(u)
        assert any(m.name == "Org-canonical MRR" for m in visible)


@pytest.mark.asyncio
async def test_acl_08_multi_crew_user_sees_union_of_crews(db_session, test_user):
    user = test_user["user"]
    s1 = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, s1)
    c1 = await _make_crew(db_session, "C1", s1, user)
    c2 = await _make_crew(db_session, "C2", s1, user)
    await _add_to_crew(db_session, user, c1)
    await _add_to_crew(db_session, user, c2)
    await db_session.flush()

    service = MetricService(db_session)
    await service.create(user, MetricCreate(name="C1 metric", scope="crew", scope_id=c1.id))
    await service.create(user, MetricCreate(name="C2 metric", scope="crew", scope_id=c2.id))

    visible = await service.list_visible(user)
    names = {m.name for m in visible}
    assert {"C1 metric", "C2 metric"}.issubset(names)


@pytest.mark.skip(
    reason=f"{PHASE} (ACL-09) — embedding ACL parity lands with the AI rewire phase"
)
@pytest.mark.asyncio
async def test_acl_09_ai_authorized_embedding_ids_matches_visible_set(db_session):
    """The embedding ACL service used by the AI retrieval path must
    match the entity-level visibility. Drift here means the chat
    answers leak data that the regular UI hides — exactly the W2
    gap red-team targeted."""
    raise NotImplementedError


@pytest.mark.asyncio
async def test_acl_10_soft_deleted_metric_is_invisible(db_session, test_user):
    user = test_user["user"]
    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="To be deleted", scope="personal", scope_id=user.id)
    )
    await service.delete(user, m.id)

    visible = await service.list_visible(user)
    assert all(row.id != m.id for row in visible)
