"""Knowledge — mutation RBAC matrix (Phase 3).

Pins the 4-scope × N-role write rules from KNOWLEDGE_REFACTOR.md §4
(MUT-01 through MUT-14). Tests run against ``MetricService`` +
``PermissionGrantService``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.metric import Metric
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.models.user_permission_grant import (
    PERMISSION_KNOWLEDGE_CERTIFY,
    UserPermissionGrant,
)
from src.schemas.metric import MetricCreate, MetricUpdate
from src.services.metric_service import MetricService
from src.services.permission_grant_service import PermissionGrantService

PHASE = "Phase 3 — Mutation gates"


# ─── helpers ───────────────────────────────────────────────────────────


async def _resolve_user(db: AsyncSession, raw) -> User:
    if hasattr(raw, "id"):
        return raw
    user_id = uuid.UUID(raw["id"]) if isinstance(raw["id"], str) else raw["id"]
    stmt = select(User).where(User.id == user_id)
    return (await db.execute(stmt)).scalar_one()


async def _make_user(db: AsyncSession, email: str, *, role: str = "admin") -> User:
    u = User(
        id=uuid.uuid4(),
        email=email,
        name=email.split("@")[0],
        password_hash=get_password_hash("x"),
        role=role,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_space(db: AsyncSession, name: str, owner: User) -> Space:
    s = Space(id=uuid.uuid4(), name=name, created_by=owner.id)
    db.add(s)
    await db.flush()
    return s


async def _add_to_space(
    db: AsyncSession, user: User, space: Space, *, role: str = "editor"
) -> None:
    db.add(SpaceMember(space_id=space.id, user_id=user.id, role=role))
    await db.flush()


async def _make_crew(db: AsyncSession, name: str, space: Space, owner: User) -> Crew:
    c = Crew(id=uuid.uuid4(), name=name, space_id=space.id, created_by=owner.id)
    db.add(c)
    await db.flush()
    return c


async def _add_to_crew(
    db: AsyncSession, user: User, crew: Crew, *, role: str = "editor"
) -> None:
    db.add(CrewMember(crew_id=crew.id, user_id=user.id, role=role))
    await db.flush()


async def _grant(
    db: AsyncSession, owner: User, target: User, permission: str
) -> UserPermissionGrant:
    return await PermissionGrantService(db).grant(
        granter=owner, target_user_id=target.id, permission=permission
    )


# ─── MUT-01..14 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mut_01_any_user_writes_to_own_personal(db_session, test_user):
    user = test_user["user"]
    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Personal", scope="personal", scope_id=user.id)
    )
    assert m.scope == "personal" and m.scope_id == user.id


@pytest.mark.asyncio
async def test_mut_02_user_cannot_write_to_other_users_personal(
    db_session, test_user, test_second_user_with_tokens
):
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    service = MetricService(db_session)

    with pytest.raises(ForbiddenError):
        await service.create(
            alice,
            MetricCreate(name="X", scope="personal", scope_id=bob.id),
        )


@pytest.mark.asyncio
async def test_mut_03_crew_commander_writes_to_own_crew(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space, role="owner")
    crew = await _make_crew(db_session, "C1", space, user)
    await _add_to_crew(db_session, user, crew, role="owner")

    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Commander metric", scope="crew", scope_id=crew.id)
    )
    assert m.scope == "crew" and m.scope_id == crew.id


@pytest.mark.asyncio
async def test_mut_04_crew_navigator_writes_to_own_crew(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space)
    crew = await _make_crew(db_session, "C1", space, user)
    await _add_to_crew(db_session, user, crew, role="editor")

    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Navigator metric", scope="crew", scope_id=crew.id)
    )
    assert m.scope == "crew"


@pytest.mark.asyncio
async def test_mut_05_crew_explorer_denied(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space)
    crew = await _make_crew(db_session, "C1", space, user)
    await _add_to_crew(db_session, user, crew, role="viewer")

    service = MetricService(db_session)
    with pytest.raises(ForbiddenError):
        await service.create(
            user, MetricCreate(name="Nope", scope="crew", scope_id=crew.id)
        )


@pytest.mark.asyncio
async def test_mut_06_commander_cannot_write_to_sibling_crew(
    db_session, test_user, test_second_user_with_tokens
):
    alice = test_user["user"]
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    space = await _make_space(db_session, "S1", alice)
    await _add_to_space(db_session, alice, space, role="owner")
    await _add_to_space(db_session, bob, space)
    c1 = await _make_crew(db_session, "C1", space, alice)
    await _add_to_crew(db_session, alice, c1, role="owner")
    c2 = await _make_crew(db_session, "C2", space, bob)
    await _add_to_crew(db_session, bob, c2, role="owner")

    service = MetricService(db_session)
    # Alice is Commander of C1 only — she cannot write to C2.
    with pytest.raises(ForbiddenError):
        await service.create(
            alice, MetricCreate(name="Cross-crew", scope="crew", scope_id=c2.id)
        )


@pytest.mark.asyncio
async def test_mut_07_space_commander_writes_to_own_space(db_session, test_user):
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space, role="owner")

    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Space metric", scope="space", scope_id=space.id)
    )
    assert m.scope == "space"


@pytest.mark.asyncio
async def test_mut_08_space_navigator_denied(db_session, test_user):
    """Space scope is stricter than Crew scope on purpose — wider blast
    radius. Navigators can co-edit inside their crew, but not at the
    space-wide level.
    """
    user = test_user["user"]
    space = await _make_space(db_session, "S1", user)
    await _add_to_space(db_session, user, space, role="editor")

    service = MetricService(db_session)
    with pytest.raises(ForbiddenError):
        await service.create(
            user, MetricCreate(name="Nope", scope="space", scope_id=space.id)
        )


@pytest.mark.asyncio
async def test_mut_09_owner_writes_to_org(db_session, test_user):
    user = test_user["user"]
    user.role = "super_admin"
    db_session.add(user)
    await db_session.flush()

    service = MetricService(db_session)
    m = await service.create(
        user, MetricCreate(name="Org canonical", scope="org", scope_id=None)
    )
    assert m.scope == "org" and m.scope_id is None


@pytest.mark.asyncio
async def test_mut_10_admin_without_certify_perm_denied_at_org(db_session, test_user):
    user = test_user["user"]
    user.role = "admin"
    db_session.add(user)
    await db_session.flush()

    service = MetricService(db_session)
    with pytest.raises(ForbiddenError):
        await service.create(
            user, MetricCreate(name="Nope", scope="org", scope_id=None)
        )


@pytest.mark.asyncio
async def test_mut_11_admin_with_certify_perm_writes_to_org(
    db_session, test_user, test_second_user_with_tokens
):
    """Headline delegation test."""
    owner = test_user["user"]
    owner.role = "owner"
    cfo = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    cfo.role = "admin"
    db_session.add_all([owner, cfo])
    await db_session.flush()

    await _grant(db_session, owner, cfo, PERMISSION_KNOWLEDGE_CERTIFY)

    service = MetricService(db_session)
    m = await service.create(
        cfo, MetricCreate(name="Org canonical via grant", scope="org", scope_id=None)
    )
    assert m.scope == "org"


@pytest.mark.asyncio
async def test_mut_12_member_denied_at_org(db_session, test_user):
    user = test_user["user"]
    user.role = "member"
    db_session.add(user)
    await db_session.flush()

    service = MetricService(db_session)
    with pytest.raises(ForbiddenError):
        await service.create(
            user, MetricCreate(name="Nope", scope="org", scope_id=None)
        )


@pytest.mark.asyncio
async def test_mut_13_revoke_knowledge_certify_blocks_admin(
    db_session, test_user, test_second_user_with_tokens
):
    owner = test_user["user"]
    owner.role = "owner"
    cfo = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    cfo.role = "admin"
    db_session.add_all([owner, cfo])
    await db_session.flush()

    grants = PermissionGrantService(db_session)
    await grants.grant(
        granter=owner, target_user_id=cfo.id, permission=PERMISSION_KNOWLEDGE_CERTIFY
    )

    service = MetricService(db_session)
    # First create succeeds while the grant is live.
    await service.create(
        cfo, MetricCreate(name="Pre-revoke", scope="org", scope_id=None)
    )

    await grants.revoke(
        revoker=owner, target_user_id=cfo.id, permission=PERMISSION_KNOWLEDGE_CERTIFY
    )

    # Subsequent writes should be denied — no caching layer.
    with pytest.raises(ForbiddenError):
        await service.create(
            cfo, MetricCreate(name="Post-revoke", scope="org", scope_id=None)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["update", "delete"])
async def test_mut_14_same_rules_apply_to_update_and_delete(
    db_session, test_user, test_second_user_with_tokens, action
):
    """Update + delete carry the same matrix as create — non-author
    users in a crew/space need the role; non-Owner non-grant users
    cannot touch Org rows."""
    alice = test_user["user"]
    alice.role = "owner"
    bob = await _resolve_user(db_session, test_second_user_with_tokens["user"])
    bob.role = "admin"
    db_session.add_all([alice, bob])
    await db_session.flush()

    service = MetricService(db_session)
    # Alice (owner) creates an Org metric. Bob (admin without grant)
    # should NOT be able to update or delete it.
    org_metric = await service.create(
        alice, MetricCreate(name="Org-canonical", scope="org", scope_id=None)
    )

    if action == "update":
        with pytest.raises(ForbiddenError):
            await service.update(
                bob, org_metric.id, MetricUpdate(description="hijack")
            )
    else:
        with pytest.raises(ForbiddenError):
            await service.delete(bob, org_metric.id)
