"""Sky-platform role hierarchy (ceo / admin / support / read_only).

These tests pin three behaviours:

* The Console reads ``users.sky_role`` as the canonical role — the
  ``CONSOLE_*_EMAILS`` env vars are now a fallback, not the primary
  source.
* A fresh Sky-team SSO login auto-seeds ``sky_role = "read_only"`` so
  the Console never displays NULL or bottoms out at the env-CSV
  precedence (which used to bury everyone at ``read_only``).
* ``UserResponse`` surfaces the field so the platform profile dropdown
  can colour-code or hide UI elements per role without an extra
  round-trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.console_auth import role_for
from src.models.user import User
from src.schemas.user import UserResponse
from src.services.auth0_service import Auth0Service


def _user(**overrides) -> User:
    base = dict(
        id=uuid.uuid4(),
        email="x@example.com",
        password_hash="x",
        name="X",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=False,
        sky_role=None,
        onboarding_version=0,
        preferences={},
        status="offline",
        is_demo=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    u = User(**base)
    u.needs_onboarding = False  # type: ignore[attr-defined]
    return u


class TestRoleFor:
    def test_db_sky_role_wins_over_env(self, monkeypatch) -> None:
        # Env says admin; DB column wins with ceo.
        monkeypatch.setenv("CONSOLE_ADMIN_EMAILS", "lucas.ventura@skyfirstlabs.com")
        u = _user(email="lucas.ventura@skyfirstlabs.com", sky_role="owner")
        assert role_for(u) == "owner"

    def test_env_admin_fallback_when_column_empty(self, monkeypatch) -> None:
        monkeypatch.setenv("CONSOLE_ADMIN_EMAILS", "gustavo@skyfirstlabs.com")
        u = _user(email="gustavo@skyfirstlabs.com", sky_role=None)
        assert role_for(u) == "admin"

    def test_env_operator_fallback_returns_support(self, monkeypatch) -> None:
        # Legacy env name remains operator; resolved value is support
        # (the ladder renamed it; old deployments keep working).
        monkeypatch.setenv("CONSOLE_OPERATOR_EMAILS", "support@skyfirstlabs.com")
        u = _user(email="support@skyfirstlabs.com", sky_role=None)
        assert role_for(u) == "support"

    def test_unknown_email_floors_to_read_only(self, monkeypatch) -> None:
        monkeypatch.delenv("CONSOLE_ADMIN_EMAILS", raising=False)
        monkeypatch.delenv("CONSOLE_OPERATOR_EMAILS", raising=False)
        u = _user(email="newhire@skyfirstlabs.com", sky_role=None)
        assert role_for(u) == "read_only"

    def test_invalid_db_value_falls_through_to_env(self, monkeypatch) -> None:
        # Defensive: if someone hand-edits the column to garbage, the
        # ladder ignores it and the env/floor takes over.
        monkeypatch.delenv("CONSOLE_ADMIN_EMAILS", raising=False)
        monkeypatch.delenv("CONSOLE_OPERATOR_EMAILS", raising=False)
        u = _user(email="x@skyfirstlabs.com", sky_role="superadmin")
        assert role_for(u) == "read_only"


class TestAutoPromoteSetsSkyRole:
    @staticmethod
    def _svc(db) -> Auth0Service:
        svc = Auth0Service.__new__(Auth0Service)
        svc.db = db
        svc.user_repo = MagicMock()
        return svc

    @pytest.mark.asyncio
    async def test_new_sky_team_user_lands_on_read_only(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = self._svc(db)
        u = _user(email="newhire@skyfirstlabs.com", is_sky_operator=False, sky_role=None)
        await svc._auto_promote_sky_team(u)
        assert u.is_sky_operator is True
        assert u.sky_role == "read_only"

    @pytest.mark.asyncio
    async def test_existing_ceo_is_not_demoted(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = self._svc(db)
        u = _user(email="lucas.ventura@skyfirstlabs.com", is_sky_operator=True, sky_role="owner")
        await svc._auto_promote_sky_team(u)
        assert u.sky_role == "owner"
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_customer_user_not_touched(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = self._svc(db)
        u = _user(email="customer@gbtsolutions.pt", is_sky_operator=False, sky_role=None)
        await svc._auto_promote_sky_team(u)
        assert u.is_sky_operator is False
        assert u.sky_role is None
        db.commit.assert_not_awaited()


class TestUserResponseSurfacesSkyRole:
    def test_default_null(self) -> None:
        u = _user(email="customer@gbtsolutions.pt", sky_role=None)
        body = UserResponse.model_validate(u).model_dump()
        assert body["sky_role"] is None

    def test_propagates_ceo(self) -> None:
        u = _user(email="lucas.ventura@skyfirstlabs.com", is_sky_operator=True, sky_role="owner")
        body = UserResponse.model_validate(u).model_dump()
        assert body["sky_role"] == "owner"
        assert body["is_sky_operator"] is True
