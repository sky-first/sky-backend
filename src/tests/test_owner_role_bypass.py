"""
Tests for the tenant founder ``super_admin`` role.

The 2026-06-03 rename moved the tenant founder from ``owner`` (which
collided with the Space / Crew / Page membership ``owner`` role) to
``super_admin``. The DB migration ``rename_role_20260603`` flipped every
existing row; this suite locks in the post-rename behaviour:

  - ``super_admin`` passes every permission, including the three
    founder-exclusive ones: ``tenant.delete``,
    ``tenant.transfer_ownership``, ``billing.manage``.
  - ``admin`` passes everything EXCEPT those three.

The file name is kept for git history continuity; the *role* under test
is ``super_admin`` now.
"""

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import ForbiddenError
from src.core.permissions import is_tenant_admin
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
# super_admin passes every permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_passes_founder_exclusive_perms(mock_db):
    founder = make_user("super_admin")
    svc = RBACService(mock_db)

    # Should not raise for any of these.
    await svc.assert_permission(founder, "tenant.delete")
    await svc.assert_permission(founder, "tenant.transfer_ownership")
    await svc.assert_permission(founder, "billing.manage")


@pytest.mark.asyncio
async def test_super_admin_passes_admin_perms(mock_db):
    founder = make_user("super_admin")
    svc = RBACService(mock_db)

    await svc.assert_permission(founder, "users.view")
    await svc.assert_permission(founder, "permissions.edit")
    await svc.assert_permission(founder, "audit.view")


@pytest.mark.asyncio
async def test_super_admin_passes_crew_content_perms(mock_db):
    founder = make_user("super_admin")
    svc = RBACService(mock_db)

    await svc.assert_permission(founder, "pages.view")
    await svc.assert_permission(founder, "dashboards.delete")
    await svc.assert_permission(founder, "agents.create")


# ---------------------------------------------------------------------------
# Admin is denied super-admin-exclusive perms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_delete_tenant(mock_db):
    admin = make_user("admin")
    svc = RBACService(mock_db)

    with pytest.raises(ForbiddenError) as exc:
        await svc.assert_permission(admin, "tenant.delete")
    assert "SuperAdmin" in str(exc.value)


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

    # Admin bypass still works for non-founder perms.
    await svc.assert_permission(admin, "users.view")
    await svc.assert_permission(admin, "audit.view")
    await svc.assert_permission(admin, "pages.create")

    # `permissions.edit` saiu daqui a 18/08/2026.
    #
    # Esta linha classificava-a como "perm não-fundador", mas a tabela de regras
    # marca-a `("tenant", "owner_only")` desde a reescrita. Os dois desenhos
    # discordavam, e a lista de exclusivas dentro do RBACService — escrita à
    # mão — seguia esta, deixando o admin editar a matriz de permissões.
    #
    # O que decide é isto: se um admin edita a matriz, o conjunto de exclusivas
    # do fundador deixa de valer nada. Ele edita a matriz e dá-se
    # `billing.manage`, `tenant.delete`, o que quiser. Os três testes acima
    # ficariam a proteger uma porta com a parede ao lado por abrir.
    #
    # Ver `test_exclusivas_do_fundador.py`.
    with pytest.raises(ForbiddenError):
        await svc.assert_permission(admin, "permissions.edit")


# ---------------------------------------------------------------------------
# Effective permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_effective_permissions_include_exclusives(mock_db):
    """get_effective_permissions returns the merged map the UI reads."""
    founder = make_user("super_admin")
    svc = RBACService(mock_db)

    eff = await svc.get_effective_permissions(founder)
    assert eff.platform_role == "super_admin"
    assert eff.permissions.get("tenant.delete") is True
    assert eff.permissions.get("tenant.transfer_ownership") is True
    assert eff.permissions.get("billing.manage") is True


@pytest.mark.asyncio
async def test_admin_effective_permissions_omit_founder_exclusives(mock_db):
    """Admin's effective map must not assert the three founder-only keys."""
    admin = make_user("admin")
    svc = RBACService(mock_db)

    eff = await svc.get_effective_permissions(admin)
    assert eff.platform_role == "admin"
    assert "tenant.delete" not in eff.permissions or eff.permissions.get("tenant.delete") is False


# ---------------------------------------------------------------------------
# Member is still denied (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_denied_founder_exclusive_regardless_of_role(mock_db):
    """A plain member must not get anywhere near tenant.delete."""
    member = make_user("member")
    svc = RBACService(mock_db)

    with pytest.raises(ForbiddenError):
        await svc.assert_permission(member, "tenant.delete")


# ---------------------------------------------------------------------------
# is_tenant_admin() helper — the canonical "is this caller a platform
# admin?" check that should be used anywhere the codebase would
# otherwise write ``user.role == "admin"``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,expected",
    [
        ("super_admin", True),
        ("admin", True),
        ("member", False),
        ("billing_admin", False),
        ("compliance_auditor", False),
        ("service_account", False),
        # Legacy values must NOT pass — the rename migration already
        # converted them at the DB layer. If a stale string survives,
        # we want a hard False so the caller stays locked out rather
        # than silently elevated.
        ("owner", False),
        ("user", False),
        ("", False),
    ],
)
def test_is_tenant_admin_matrix(role: str, expected: bool):
    assert is_tenant_admin(make_user(role)) is expected
