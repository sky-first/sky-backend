"""Data/Content plane membership enforcement (Option B, 2026-06).

Platform role (super_admin/admin) governs MANAGEMENT, not data access.
Content keys in ``DATA_PLANE_PERMS`` must require real Space/Crew
membership — an admin who is NOT a member is denied content; management
keys keep the admin bypass; personal-mode queries are exempt.

These assert at the RBACService.assert_permission layer (the central gate)
for the three profiles: member / admin-non-member / outside-space.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.core.security import get_password_hash
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.rbac_service import RBACService


async def _user(db: AsyncSession, role: str, name: str) -> User:
    u = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("pw"),
        name=name,
        role=role,
    )
    db.add(u)
    await db.flush()
    return u


async def _space(db: AsyncSession, owner: User) -> Space:
    s = Space(name=f"Space-{uuid.uuid4().hex[:6]}", created_by=owner.id)
    db.add(s)
    await db.flush()
    return s


async def _add_member(db: AsyncSession, space: Space, user: User, role: str = "viewer") -> None:
    db.add(SpaceMember(space_id=space.id, user_id=user.id, role=role))
    await db.flush()


@pytest.mark.asyncio
async def test_admin_non_member_denied_content_query(db_session: AsyncSession):
    """A platform ADMIN who is NOT a member of the space is DENIED ai.query
    (previously the admin bypass let them through)."""
    rbac = RBACService(db_session)
    owner = await _user(db_session, "member", "owner")
    space = await _space(db_session, owner)
    await _add_member(db_session, space, owner, "owner")
    admin = await _user(db_session, "admin", "admin")  # NOT a member
    await db_session.commit()

    with pytest.raises(ForbiddenError):
        await rbac.assert_permission(admin, "ai.query", space_id=space.id)


@pytest.mark.asyncio
async def test_super_admin_non_member_denied_content_query(db_session: AsyncSession):
    """super_admin is also gated on the data plane — no god-mode on content."""
    rbac = RBACService(db_session)
    owner = await _user(db_session, "member", "owner")
    space = await _space(db_session, owner)
    await _add_member(db_session, space, owner, "owner")
    sa = await _user(db_session, "super_admin", "sa")  # NOT a member
    await db_session.commit()

    with pytest.raises(ForbiddenError):
        await rbac.assert_permission(sa, "ai.query", space_id=space.id)


@pytest.mark.asyncio
async def test_space_member_allowed_content_query(db_session: AsyncSession):
    """A plain member (viewer) of the space CAN run the content query."""
    rbac = RBACService(db_session)
    owner = await _user(db_session, "member", "owner")
    space = await _space(db_session, owner)
    await _add_member(db_session, space, owner, "owner")
    viewer = await _user(db_session, "member", "viewer")
    await _add_member(db_session, space, viewer, "viewer")
    await db_session.commit()

    # Should NOT raise.
    await rbac.assert_permission(viewer, "ai.query", space_id=space.id)


@pytest.mark.asyncio
async def test_admin_findings_denied_when_non_member(db_session: AsyncSession):
    """Agent insights/findings are content too — admin non-member denied."""
    rbac = RBACService(db_session)
    owner = await _user(db_session, "member", "owner")
    space = await _space(db_session, owner)
    await _add_member(db_session, space, owner, "owner")
    admin = await _user(db_session, "admin", "admin")
    await db_session.commit()

    with pytest.raises(ForbiddenError):
        await rbac.assert_permission(admin, "agents.findings.view", space_id=space.id)


@pytest.mark.asyncio
async def test_admin_management_key_still_bypasses(db_session: AsyncSession):
    """MANAGEMENT keys keep the admin bypass — admin can still create spaces
    without being a member of anything."""
    rbac = RBACService(db_session)
    admin = await _user(db_session, "admin", "admin")
    await db_session.commit()

    # Should NOT raise — management plane is unaffected.
    await rbac.assert_permission(admin, "spaces.create")


@pytest.mark.asyncio
async def test_personal_query_not_gated_for_admin(db_session: AsyncSession):
    """Personal-mode query (no space/crew) is exempt — not a data-plane key."""
    rbac = RBACService(db_session)
    admin = await _user(db_session, "admin", "admin")
    await db_session.commit()

    # ai.query.personal is NOT in DATA_PLANE_PERMS → admin bypass applies.
    await rbac.assert_permission(admin, "ai.query.personal")
