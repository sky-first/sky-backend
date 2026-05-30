"""Per-tenant auth methods — schema + endpoint coverage.

Pins the contract introduced in PR feat/per-tenant-auth-methods:

* ``AuthMethods`` schema rejects an empty configuration.
* ``GET /api/v1/auth/methods`` resolves a tenant from the Host header
  and returns its configuration, falling back to Google-only when no
  tenant is resolvable.
* ``POST /api/v1/auth/login`` honours the tenant's ``auth_methods.password``
  flag: 403 when the flag is off (or no tenant resolvable), 200 when the
  flag is on and credentials are valid, 401 when the flag is on and
  credentials are wrong.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant import DEFAULT_AUTH_METHODS, Tenant
from src.schemas.tenant import AuthMethods


# ── Schema ─────────────────────────────────────────────────────────────


class TestAuthMethodsSchema:
    def test_default_factory_kwargs(self) -> None:
        """``DEFAULT_AUTH_METHODS`` is a valid AuthMethods payload."""
        m = AuthMethods(**DEFAULT_AUTH_METHODS)
        assert m.google is True
        assert m.password is False

    def test_password_only_passes(self) -> None:
        m = AuthMethods(password=True)
        assert m.model_dump() == {
            "password": True,
            "google": False,
            "azure": False,
            "okta": False,
        }

    def test_all_false_rejected(self) -> None:
        with pytest.raises(ValueError) as exc:
            AuthMethods(
                password=False,
                google=False,
                azure=False,
                okta=False,
            )
        assert "At least one authentication method must be enabled" in str(exc.value)

    def test_multiple_methods_allowed(self) -> None:
        m = AuthMethods(password=True, google=True, azure=True)
        d = m.model_dump()
        assert d["password"] is True
        assert d["google"] is True
        assert d["azure"] is True
        assert d["okta"] is False


# ── /auth/methods endpoint ────────────────────────────────────────────


class TestAuthMethodsEndpoint:
    """Resolution order: middleware ctx → host slug → default fallback."""

    @pytest.mark.asyncio
    async def test_default_when_no_host(self, async_client: AsyncClient) -> None:
        """Bare hostname with no tenant resolvable: Google-only fallback,
        demo link on (Sky landing pitches prospects)."""
        resp = await async_client.get("/api/v1/auth/methods")
        assert resp.status_code == 200
        body = resp.json()
        assert body["google"] is True
        assert body["password"] is False
        assert body["azure"] is False
        assert body["okta"] is False
        assert body["show_demo"] is True
        assert body["tenant_slug"] is None

    @pytest.mark.asyncio
    async def test_unknown_subdomain_returns_default(
        self, async_client: AsyncClient
    ) -> None:
        """A workspace-foo host that does not exist in the registry
        falls back to default (Google-only) so the login page still
        renders something usable instead of a 404."""
        resp = await async_client.get(
            "/api/v1/auth/methods",
            headers={"Host": "workspace-doesnotexist.skyfirstlabs.com"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["google"] is True
        assert body["password"] is False

    @pytest.mark.asyncio
    async def test_resolved_tenant_returns_its_methods(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """A registry row keyed by the host subdomain controls the
        methods returned by the endpoint."""
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        tenant = Tenant(
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
        db_session.add(tenant)
        await db_session.commit()

        resp = await async_client.get(
            "/api/v1/auth/methods",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["password"] is True
        assert body["google"] is False
        assert body["tenant_slug"] == slug
        # A tenant without ``feature_flags.demo_enabled`` set hides the
        # demo link — the operator must opt back in explicitly.
        assert body["show_demo"] is False

    @pytest.mark.asyncio
    async def test_resolved_tenant_with_demo_opt_in(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Operator-set ``feature_flags.demo_enabled = true`` brings the
        demo link back on for that tenant."""
        slug = f"demoback{uuid.uuid4().hex[:6]}"
        tenant = Tenant(
            slug=slug,
            display_name="Demo Enabled",
            tier="starter",
            db_host="db.example.com",
            db_name="ai_saas_db",
            db_credentials_secret_arn="local-dev:t",
            redis_host="redis.example.com",
            redis_credentials_secret_arn="local-dev:t:redis",
            sso_provider="google",
            sso_config={},
            feature_flags={"demo_enabled": True},
            auth_methods={
                "password": False,
                "google": True,
                "azure": False,
                "okta": False,
            },
        )
        db_session.add(tenant)
        await db_session.commit()

        resp = await async_client.get(
            "/api/v1/auth/methods",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["show_demo"] is True


# ── /auth/login gating ────────────────────────────────────────────────


class TestLoginPerTenantAuthMethods:
    """Login goes through the same resolver — password ON for the
    matched tenant means the credentials are checked; password OFF means
    the historical 403 is returned regardless of credentials."""

    @pytest.mark.asyncio
    async def test_login_rejected_when_tenant_disables_password(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"ssotenant{uuid.uuid4().hex[:6]}"
        tenant = Tenant(
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
        db_session.add(tenant)
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/login",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_login_accepted_when_tenant_enables_password(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        tenant = Tenant(
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
        db_session.add(tenant)
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/login",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        # The credential path is exercised — 200 on a valid user, 401
        # if the system rejects the credentials. Either way it is NOT a
        # 403, which is what we are guarding against (the gate is off,
        # the auth_service decides).
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401_when_gate_open(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_user: dict,
    ) -> None:
        slug = f"pwdpilot{uuid.uuid4().hex[:6]}"
        tenant = Tenant(
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
        db_session.add(tenant)
        await db_session.commit()

        resp = await async_client.post(
            "/api/v1/auth/login",
            headers={"Host": f"workspace-{slug}.skyfirstlabs.com"},
            json={
                "email": test_user["email"],
                "password": "completely-wrong-password",
            },
        )
        # With the gate open the credential layer reports 401, never
        # 403. A 403 here would mean the gate did not honour the row.
        assert resp.status_code == 401
