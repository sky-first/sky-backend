"""Auto-promote @skyfirstlabs.com users to is_sky_operator on SSO login.

A Sky engineer who signs in through Google for the first time should
land with ``is_sky_operator = true`` so they can browse /console
without any out-of-band SQL. Equally, an engineer whose row was
created before the column existed (or before the seed migration
landed) should be flipped on the next sign-in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.services.auth0_service import Auth0Service


# ── Pure helpers ──────────────────────────────────────────────────────


class TestIsSkyTeamEmail:
    def test_skyfirstlabs_domain_recognised(self) -> None:
        assert Auth0Service._is_sky_team_email("lucas.ventura@skyfirstlabs.com")
        assert Auth0Service._is_sky_team_email("GUSTAVO@SkyFirstLabs.com")
        assert Auth0Service._is_sky_team_email("  paulo@skyfirstlabs.com  ")

    def test_other_domains_rejected(self) -> None:
        assert not Auth0Service._is_sky_team_email("lucas@gbtsolutions.pt")
        assert not Auth0Service._is_sky_team_email("admin@gmail.com")
        assert not Auth0Service._is_sky_team_email("")
        assert not Auth0Service._is_sky_team_email(None)
        # No partial / lookalike matches.
        assert not Auth0Service._is_sky_team_email("attacker@skyfirstlabs.com.evil.tld")
        assert not Auth0Service._is_sky_team_email("attacker@notskyfirstlabs.com")


# ── DB-touching helper ────────────────────────────────────────────────


def _make_service(db: AsyncSession) -> Auth0Service:
    """Construct an Auth0Service without the rest of the SSO machinery."""
    svc = Auth0Service.__new__(Auth0Service)
    svc.db = db
    svc.user_repo = MagicMock()
    return svc


class TestAutoPromoteSkyTeam:
    @pytest.mark.asyncio
    async def test_skyfirstlabs_user_promoted(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = _make_service(db)
        user = User(
            email="lucas.ventura@skyfirstlabs.com",
            password_hash="x",
            name="Lucas",
            role="user",
            email_verified=True,
            is_sky_operator=False,
        )
        await svc._auto_promote_sky_team(user)
        assert user.is_sky_operator is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_external_user_not_touched(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = _make_service(db)
        user = User(
            email="customer@gbtsolutions.pt",
            password_hash="x",
            name="Customer",
            role="user",
            email_verified=True,
            is_sky_operator=False,
        )
        await svc._auto_promote_sky_team(user)
        assert user.is_sky_operator is False
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_promoted_short_circuits(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = _make_service(db)
        user = User(
            email="paulo.bomfim@skyfirstlabs.com",
            password_hash="x",
            name="Paulo",
            role="user",
            email_verified=True,
            is_sky_operator=True,
            # Already has the sky_role seeded — auto-promote has nothing
            # to do and must not touch the DB.
            sky_role="admin",
        )
        await svc._auto_promote_sky_team(user)
        assert user.is_sky_operator is True
        assert user.sky_role == "admin"
        db.commit.assert_not_awaited()


# ── JIT gate single-tenant exemption ──────────────────────────────────


class TestSkyOperatorJITGateSingleTenant:
    """In single-tenant deployments (``MULTI_TENANT_ENABLED = False``) the
    Sky operator IS the platform, so the JIT consent gate must not
    block them. The check should only fire when multi-tenant is on."""

    @pytest.mark.asyncio
    async def test_single_tenant_skips_jit(self, monkeypatch) -> None:
        from src.config.settings import settings
        from src.services.rbac_service import _is_sky_operator_without_jit

        monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", False)
        db = AsyncMock(spec=AsyncSession)
        user = User(
            email="lucas.ventura@skyfirstlabs.com",
            password_hash="x",
            name="Lucas",
            role="user",
            email_verified=True,
            is_sky_operator=True,
        )
        # Operator with no support_sessions row at all is NOT blocked in
        # single-tenant mode.
        assert await _is_sky_operator_without_jit(user, db) is False
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_operator_never_blocked(self, monkeypatch) -> None:
        from src.config.settings import settings
        from src.services.rbac_service import _is_sky_operator_without_jit

        # Multi-tenant on, but the caller is a regular customer user.
        monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
        db = AsyncMock(spec=AsyncSession)
        user = User(
            email="customer@gbtsolutions.pt",
            password_hash="x",
            name="Customer",
            role="user",
            email_verified=True,
            is_sky_operator=False,
        )
        assert await _is_sky_operator_without_jit(user, db) is False


# ── JIT gate home-tenant exemption (multi-tenant mode) ─────────────────


class TestSkyOperatorJITGateHomeTenant:
    """Even with ``MULTI_TENANT_ENABLED = True``, a Sky operator working
    on the platform's own *default* context (the platform host, which the
    resolver maps to ``is_default``) is on home turf and must not be
    gated. Only cross-tenant access (a real customer tenant) requires an
    active ``support_sessions`` row. Regression guard for the staging
    incident where operators were 403'd on sky-stg after multi-tenant was
    re-enabled."""

    @pytest.mark.asyncio
    async def test_home_tenant_skips_jit(self, monkeypatch) -> None:
        from src.config.settings import settings
        from src.core.tenant_context import (
            DEFAULT_TENANT_CONTEXT,
            reset_current_tenant,
            set_current_tenant,
        )
        from src.services.rbac_service import _is_sky_operator_without_jit

        monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
        db = AsyncMock(spec=AsyncSession)
        user = User(
            email="gustavo.mendonca@skyfirstlabs.com",
            password_hash="x",
            name="Gustavo",
            role="user",
            email_verified=True,
            is_sky_operator=True,
        )
        token = set_current_tenant(DEFAULT_TENANT_CONTEXT)
        try:
            # Home/default context → no JIT required, no DB lookup.
            assert await _is_sky_operator_without_jit(user, db) is False
            db.execute.assert_not_awaited()
        finally:
            reset_current_tenant(token)

    @pytest.mark.asyncio
    async def test_cross_tenant_without_session_blocked(self, monkeypatch) -> None:
        from uuid import uuid4

        from src.config.settings import settings
        from src.core.tenant_context import (
            TenantContext,
            reset_current_tenant,
            set_current_tenant,
        )
        from src.services.rbac_service import _is_sky_operator_without_jit

        monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)

        # No active support_sessions row for this operator.
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db = AsyncMock(spec=AsyncSession)
        db.execute.return_value = result

        user = User(
            email="gustavo.mendonca@skyfirstlabs.com",
            password_hash="x",
            name="Gustavo",
            role="user",
            email_verified=True,
            is_sky_operator=True,
        )
        customer_ctx = TenantContext(
            slug="gbtsolutions",
            id=uuid4(),
            tier="starter",
            display_name="GBT Solutions",
        )
        token = set_current_tenant(customer_ctx)
        try:
            # Cross-tenant + no JIT session → blocked.
            assert await _is_sky_operator_without_jit(user, db) is True
            db.execute.assert_awaited_once()
        finally:
            reset_current_tenant(token)
