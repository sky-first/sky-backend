"""Password recovery (forgot-password / reset-password) end-to-end.

Pins the contract for the self-service reset flow:

* ``POST /auth/forgot-password`` on a password-enabled tenant returns a
  generic 200 AND mints a reset token on the matching user.
* ``forgot-password`` for an unknown email still returns the SAME generic
  200 and sets nothing — no account-existence leak.
* ``forgot-password`` on an SSO-only tenant (no password method) is
  blocked with 403, mirroring the /login gate.
* ``POST /auth/reset-password`` with a valid, unexpired token changes the
  password and clears the token.
* ``reset-password`` with an expired or unknown token returns 400.

The async_client uses ``Host: test`` which resolves to no tenant, so
each test that needs the password gate ON creates a registry row keyed
on a ``workspace-<slug>`` host and sends that Host header — exactly like
``test_auth_methods_per_tenant.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import verify_password
from src.models.tenant import Tenant
from src.models.user import User


def _password_tenant(slug: str) -> Tenant:
    """A registry row that allows password auth (so the gate is open)."""
    return Tenant(
        slug=slug,
        display_name="Password Pilot",
        tier="starter",
        db_host="db.example.com",
        db_name="ai_saas_db",
        db_credentials_secret_arn="local-dev:t",
        redis_host="redis.example.com",
        redis_credentials_secret_arn="local-dev:t:redis",
        sso_provider="local",
        sso_config={},
        feature_flags={},
        auth_methods={
            "password": True,
            "google": False,
            "azure": False,
            "okta": False,
        },
    )


def _sso_only_tenant(slug: str) -> Tenant:
    """A registry row that disables password auth (SSO-only)."""
    return Tenant(
        slug=slug,
        display_name="SSO Only",
        tier="starter",
        db_host="db.example.com",
        db_name="ai_saas_db",
        db_credentials_secret_arn="local-dev:t",
        redis_host="redis.example.com",
        redis_credentials_secret_arn="local-dev:t:redis",
        sso_provider="google",
        sso_config={},
        feature_flags={},
        auth_methods={
            "password": False,
            "google": True,
            "azure": False,
            "okta": False,
        },
    )


async def _reload(db: AsyncSession, user_id) -> User:
    res = await db.execute(select(User).where(User.id == user_id))
    return res.scalar_one()


class TestForgotPassword:
    @pytest.mark.asyncio
    async def test_forgot_for_password_tenant_returns_200_and_sets_token(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        db_session.add(_password_tenant(slug))
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/forgot-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"email": test_user["email"]},
        )
        assert resp.status_code == 200

        user = await _reload(db_session, test_user["user"].id)
        assert user.password_reset_token is not None
        assert user.password_reset_expires_at is not None

    @pytest.mark.asyncio
    async def test_forgot_for_unknown_email_returns_200_and_sets_nothing(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        """No account-existence leak: same generic 200, no token minted
        anywhere (the known user's row stays clean too)."""
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        db_session.add(_password_tenant(slug))
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/forgot-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"email": f"nobody-{uuid.uuid4().hex}@example.com"},
        )
        assert resp.status_code == 200

        # The pre-existing real user must NOT have a reset token set by an
        # unrelated forgot request.
        user = await _reload(db_session, test_user["user"].id)
        assert user.password_reset_token is None
        assert user.password_reset_expires_at is None

    @pytest.mark.asyncio
    async def test_forgot_blocked_for_sso_only_tenant(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"ssotenant{uuid.uuid4().hex[:6]}"
        db_session.add(_sso_only_tenant(slug))
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/forgot-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"email": test_user["email"]},
        )
        assert resp.status_code == 403

        # Gate refused before any token was minted.
        user = await _reload(db_session, test_user["user"].id)
        assert user.password_reset_token is None


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_reset_with_valid_token_changes_password(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        db_session.add(_password_tenant(slug))

        # Seed a valid (unexpired) reset token directly on the user.
        token = "valid-reset-token-" + uuid.uuid4().hex
        user = await _reload(db_session, test_user["user"].id)
        user.password_reset_token = token
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await db_session.commit()

        new_password = "BrandNewPassw0rd!"
        resp = await async_client.post(
            "/api/v1/auth/reset-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"token": token, "new_password": new_password},
        )
        assert resp.status_code == 200

        user = await _reload(db_session, test_user["user"].id)
        # Token cleared (single use) and the new password verifies.
        assert user.password_reset_token is None
        assert user.password_reset_expires_at is None
        assert verify_password(new_password, user.password_hash)

    @pytest.mark.asyncio
    async def test_reset_with_expired_token_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        db_session.add(_password_tenant(slug))

        token = "expired-reset-token-" + uuid.uuid4().hex
        user = await _reload(db_session, test_user["user"].id)
        original_hash = user.password_hash
        user.password_reset_token = token
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/reset-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"token": token, "new_password": "DoesntMatter123!"},
        )
        assert resp.status_code == 400

        user = await _reload(db_session, test_user["user"].id)
        # Password unchanged on a failed reset.
        assert user.password_hash == original_hash

    @pytest.mark.asyncio
    async def test_reset_with_unknown_token_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        db_session.add(_password_tenant(slug))
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/reset-password",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={"token": "this-token-does-not-exist", "new_password": "Whatever123!"},
        )
        assert resp.status_code == 400
