"""Unit tests for the Phase 1 RBAC rewrite — Authorization resolver.

Validates the deterministic translation of permission keys into
(scope, required_level) decisions. Replaces what the old 14×80 editable
matrix encoded across hundreds of dict entries with a small, audited
test surface.

Coverage matrix (15 cases):

  Platform pivots (no Space context):
    1. owner   → tenant.delete           (owner-only)         → allow
    2. admin   → tenant.delete           (owner-only)         → deny
    3. owner   → billing.manage          (owner-only)         → allow
    4. admin   → audit.view              (admin_or_above)     → allow
    5. member  → audit.view              (admin_or_above)     → deny
    6. member  → spaces.create           (any_member)         → allow

  Space-scoped (member with explicit Space role):
    7. member + viewer  → ai.query               (viewer)     → allow
    8. member + viewer  → connections.create     (editor)     → deny
    9. member + editor  → connections.create     (editor)     → allow
   10. member + editor  → spaces.members.manage  (owner)      → deny
   11. member + owner   → spaces.members.manage  (owner)      → allow

  Negative — unknown permission key:
   12. owner   → "no.such.key"          → deny
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.repositories.user import UserRepository
from src.services.authorization import Authorization


# ── helpers ─────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession, *, role: str, name: str) -> User:
    repo = UserRepository(db)
    return await repo.create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name=name,
        role=role,
    )


async def _space_with_member(
    db: AsyncSession, owner: User, member: User, role: str
) -> Space:
    space = Space(name=f"Space {uuid4().hex[:6]}", created_by=owner.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=member.id, role=role))
    await db.commit()
    await db.refresh(space)
    return space


# ── Platform pivots ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_tenant_delete(db_session):
    user = await _user(db_session, role="owner", name="O")
    assert await Authorization(db_session).can(user, "tenant.delete") is True


@pytest.mark.asyncio
async def test_admin_cannot_tenant_delete(db_session):
    user = await _user(db_session, role="admin", name="A")
    assert await Authorization(db_session).can(user, "tenant.delete") is False


@pytest.mark.asyncio
async def test_owner_can_billing_manage(db_session):
    user = await _user(db_session, role="owner", name="O")
    assert await Authorization(db_session).can(user, "billing.manage") is True


@pytest.mark.asyncio
async def test_admin_can_audit_view(db_session):
    user = await _user(db_session, role="admin", name="A")
    assert await Authorization(db_session).can(user, "audit.view") is True


@pytest.mark.asyncio
async def test_member_cannot_audit_view(db_session):
    user = await _user(db_session, role="member", name="M")
    assert await Authorization(db_session).can(user, "audit.view") is False


@pytest.mark.asyncio
async def test_any_member_can_create_space(db_session):
    user = await _user(db_session, role="member", name="M")
    assert await Authorization(db_session).can(user, "spaces.create") is True


# ── Space-scoped (canonical roles) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_can_run_ai_query(db_session):
    owner = await _user(db_session, role="admin", name="Owner")
    user = await _user(db_session, role="member", name="V")
    space = await _space_with_member(db_session, owner, user, "viewer")
    assert (
        await Authorization(db_session).can(user, "ai.query", space_id=space.id)
        is True
    )


@pytest.mark.asyncio
async def test_viewer_cannot_create_connection(db_session):
    owner = await _user(db_session, role="admin", name="Owner")
    user = await _user(db_session, role="member", name="V")
    space = await _space_with_member(db_session, owner, user, "viewer")
    assert (
        await Authorization(db_session).can(
            user, "connections.create", space_id=space.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_editor_can_create_connection(db_session):
    owner = await _user(db_session, role="admin", name="Owner")
    user = await _user(db_session, role="member", name="E")
    space = await _space_with_member(db_session, owner, user, "editor")
    assert (
        await Authorization(db_session).can(
            user, "connections.create", space_id=space.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_editor_cannot_manage_members(db_session):
    owner = await _user(db_session, role="admin", name="Owner")
    user = await _user(db_session, role="member", name="E")
    space = await _space_with_member(db_session, owner, user, "editor")
    assert (
        await Authorization(db_session).can(
            user, "spaces.members.manage", space_id=space.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_space_owner_can_manage_members(db_session):
    creator = await _user(db_session, role="admin", name="Owner")
    user = await _user(db_session, role="member", name="SO")
    space = await _space_with_member(db_session, creator, user, "owner")
    assert (
        await Authorization(db_session).can(
            user, "spaces.members.manage", space_id=space.id
        )
        is True
    )



# ── Negative ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_permission_key_denies_even_for_owner(db_session):
    user = await _user(db_session, role="owner", name="O")
    # Defense-in-depth: unknown keys deny even for Owner. New permission
    # keys must be explicitly registered in PERMISSION_RULES; this prevents
    # silent allow if a typo or removal slips through during the rewrite.
    assert await Authorization(db_session).can(user, "no.such.key") is False


@pytest.mark.asyncio
async def test_unknown_permission_key_denies_member(db_session):
    user = await _user(db_session, role="member", name="M")
    assert await Authorization(db_session).can(user, "no.such.key") is False
