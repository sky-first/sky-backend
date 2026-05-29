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
        )
        await svc._auto_promote_sky_team(user)
        # Still true and no redundant commit.
        assert user.is_sky_operator is True
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
