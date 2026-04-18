"""
Tests for Owner platform role (ADR-002 Wave 1 backend).

Owner is the tenant founder — single seat, sits above Admin. Owner passes
every permission including three exclusives: tenant.delete,
tenant.transfer_ownership, billing.manage.

Admin passes everything EXCEPT those three. This gap is the difference
between "powerful user" and "irrevocable founder".
"""
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import ForbiddenError
from src.services.rbac_service import RBACService


def make_user(role: str):
    """Build a throwaway User-like object with just the fields RBACService reads."""
    return SimpleNamespace(id=uuid4(), email=f"{role}@x.com", role=role, is_sky_operator=False)


@pytest.fixture
def mock_db():
    """DB session mock that supports .execute / .scalar_one_or_none / .flush."""
    db = MagicMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute.return_value = result
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Owner passes every permission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owner_passes_owner_exclusive_perms(mock_db):
    owner = make_user("owner")
    svc = RBACService(mock_db)

    # Should not raise for any of these.
    await svc.assert_permission(owner, "tenant.delete")
    await svc.assert_permission(owner, "tenant.transfer_ownership")
    await svc.assert_permission(owner, "billing.manage")


@pytest.mark.asyncio
async def test_owner_passes_admin_perms(mock_db):
    owner = make_user("owner")
    svc = RBACService(mock_db)

    await svc.assert_permission(owner, "users.view")
    await svc.assert_permission(owner, "permissions.edit")
    await svc.assert_permission(owner, "audit.view")


@pytest.mark.asyncio
async def test_owner_passes_crew_content_perms(mock_db):
    owner = make_user("owner")
    svc = RBACService(mock_db)

    await svc.assert_permission(owner, "pages.view")
    await svc.assert_permission(owner, "dashboards.delete")
    await svc.assert_permission(owner, "agents.create")


# ---------------------------------------------------------------------------
# Admin is denied owner-exclusive perms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_cannot_delete_tenant(mock_db):
    admin = make_user("admin")
    svc = RBACService(mock_db)

    with pytest.raises(ForbiddenError) as exc:
        await svc.assert_permission(admin, "tenant.delete")
    assert "Owner" in str(exc.value)


@pytest.mark.asyncio
async def test_admin_cannot_transfer_ownership(mock_db):
    admin = make_user("admin")
    svc = RBACService(mock_db)

    with pytest.raises(ForbiddenError):
        await svc.assert_permission(admin, "tenant.transfer_ownership")


@pytest.mark.asyncio
async def test_admin_cannot_manage_billing(mock_db):
    admin = make_user("admin")
    svc = RBACService(mock_db)

    with pytest.raises(ForbiddenError):
        await svc.assert_permission(admin, "billing.manage")


@pytest.mark.asyncio
async def test_admin_still_passes_everything_else(mock_db):
    admin = make_user("admin")
    svc = RBACService(mock_db)

    # Admin bypass still works for non-owner perms.
    await svc.assert_permission(admin, "users.view")
    await svc.assert_permission(admin, "audit.view")
    await svc.assert_permission(admin, "permissions.edit")
    await svc.assert_permission(admin, "pages.create")


# ---------------------------------------------------------------------------
# Effective permissions for Owner includes the three exclusives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owner_effective_permissions_include_exclusives(mock_db):
    """get_effective_permissions returns the merged map the UI reads."""
    owner = make_user("owner")
    svc = RBACService(mock_db)

    eff = await svc.get_effective_permissions(owner)
    assert eff.platform_role == "owner"
    assert eff.permissions.get("tenant.delete") is True
    assert eff.permissions.get("tenant.transfer_ownership") is True
    assert eff.permissions.get("billing.manage") is True


@pytest.mark.asyncio
async def test_admin_effective_permissions_omit_owner_exclusives(mock_db):
    """Admin's effective map should NOT contain the three owner-exclusives."""
    admin = make_user("admin")
    svc = RBACService(mock_db)

    eff = await svc.get_effective_permissions(admin)
    assert eff.platform_role == "admin"
    # Admin effective map doesn't assert the three keys because they're not
    # in DEFAULT_ROLE_PERMISSIONS. assert_permission draws the line at
    # enforcement time.
    assert "tenant.delete" not in eff.permissions or eff.permissions.get("tenant.delete") is False


# ---------------------------------------------------------------------------
# Crew roles still denied everything admin-level (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commander_denied_owner_exclusive_regardless_of_role(mock_db):
    """A plain commander must not get anywhere near tenant.delete."""
    commander = make_user("commander")
    svc = RBACService(mock_db)

    # No crew/space context + not admin/owner → falls through to effective
    # check which won't have owner-exclusive keys as True.
    with pytest.raises(ForbiddenError):
        await svc.assert_permission(commander, "tenant.delete")
