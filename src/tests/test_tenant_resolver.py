"""Tests for the tenant resolver middleware (Projeto A — PR #2).

The middleware ships in a no-op mode while ``MULTI_TENANT_ENABLED`` is
False — that is the default and the only behaviour exercised in CI for
the foundation PRs. The flag-ON paths (subdomain extraction, header
priority, registry lookup, 404 on unknown slug) are also tested by
flipping the setting inside the test.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from src.api.middleware.tenant_resolver import (
    _resolve_context,
    _slug_from_host,
    _slug_from_jwt,
    clear_tenant_cache,
)
from src.config.settings import settings
from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)
from src.models.tenant import Tenant


# ─── Helpers ────────────────────────────────────────────────────────


class _FakeRequest:
    """Minimal stand-in for ``starlette.Request`` good enough for the
    resolver's needs — it only reads ``.headers`` and ``.url.path``."""

    def __init__(self, headers=None, path="/api/v1/anything"):
        self.headers = headers or {}

        class _URL:
            def __init__(self, p):
                self.path = p

        self.url = _URL(path)


def _persist_tenant(session, **overrides):
    base = dict(
        slug="gbt",
        display_name="GBT S.A.",
        tier="starter",
        db_host="postgres-gbt.tenant-data-gbt.svc.cluster.local",
        db_port=5432,
        db_name="gbt",
        db_credentials_secret_arn="arn:postgres",
        redis_host="redis-gbt.tenant-data-gbt.svc.cluster.local",
        redis_credentials_secret_arn="arn:redis",
        sso_provider="google",
    )
    base.update(overrides)
    tenant = Tenant(id=uuid.uuid4(), **base)
    session.add(tenant)
    return tenant


@asynccontextmanager
async def _patch_session_local(target_session):
    """Redirect ``AsyncSessionLocal`` used by the resolver to a session
    factory that yields ``target_session`` — the unit test fixture
    runs against in-memory SQLite, not against the global engine."""

    from src.api.middleware import tenant_resolver as tr_module

    class _Factory:
        def __call__(self):
            return _CtxWrap(target_session)

    class _CtxWrap:
        def __init__(self, s):
            self._s = s

        async def __aenter__(self):
            return self._s

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original = tr_module.AsyncSessionLocal
    tr_module.AsyncSessionLocal = _Factory()
    try:
        yield
    finally:
        tr_module.AsyncSessionLocal = original


# ─── Subdomain parsing ──────────────────────────────────────────────


class TestSlugFromHost:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("workspace-gbt.skyfirstlabs.com", "gbt"),
            ("workspace-gbt-stg.skyfirstlabs.com", "gbt"),
            ("api-gbt.skyfirstlabs.com", "gbt"),
            ("api-gbt-stg.skyfirstlabs.com", "gbt"),
            ("WORKSPACE-GBT.skyfirstlabs.com", "gbt"),  # case-insensitive
            ("workspace-gbt.skyfirstlabs.com:8000", "gbt"),  # port stripped
            ("workspace-some-client.skyfirstlabs.com", "some-client"),
        ],
    )
    def test_accepts(self, host, expected):
        assert _slug_from_host(host) == expected

    @pytest.mark.parametrize(
        "host",
        [
            None,
            "",
            "api.skyfirstlabs.com",  # no slug
            "workspace-.skyfirstlabs.com",  # empty slug
            "skyfirstlabs.com",
            "demo.skyfirstlabs.com",  # demo is not a tenant
        ],
    )
    def test_rejects(self, host):
        assert _slug_from_host(host) is None


# ─── JWT extraction ────────────────────────────────────────────────


class TestSlugFromJwt:
    def test_returns_none_without_bearer(self):
        assert _slug_from_jwt(None) is None
        assert _slug_from_jwt("") is None
        assert _slug_from_jwt("Basic abc") is None

    def test_returns_none_on_invalid_token(self):
        assert _slug_from_jwt("Bearer not-a-real-jwt") is None

    def test_extracts_slug_from_valid_token(self):
        from src.core.security import create_access_token

        # ``create_access_token(data: dict)`` signs and returns the JWT.
        token = create_access_token(
            {"sub": "user@example.com", "tenant_slug": "gbt"}
        )
        assert _slug_from_jwt(f"Bearer {token}") == "gbt"


# ─── Resolver with flag OFF ────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_returns_default_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", False)
    clear_tenant_cache()

    # Even a perfectly-formed host header is ignored while the flag is OFF.
    req = _FakeRequest(headers={"host": "workspace-gbt.skyfirstlabs.com"})
    ctx, bad = await _resolve_context(req)

    assert ctx is DEFAULT_TENANT_CONTEXT
    assert ctx.is_default is True
    assert bad is None


# ─── Resolver with flag ON ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_loads_from_registry(monkeypatch, db_session):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    clear_tenant_cache()

    _persist_tenant(db_session, slug="gbt")
    await db_session.commit()

    async with _patch_session_local(db_session):
        req = _FakeRequest(headers={"host": "workspace-gbt.skyfirstlabs.com"})
        ctx, bad = await _resolve_context(req)

    assert bad is None
    assert ctx.slug == "gbt"
    assert ctx.is_default is False
    assert ctx.tier == "starter"


@pytest.mark.asyncio
async def test_resolver_uses_header_when_host_does_not_match(monkeypatch, db_session):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    clear_tenant_cache()

    _persist_tenant(db_session, slug="gbt")
    await db_session.commit()

    async with _patch_session_local(db_session):
        req = _FakeRequest(
            headers={
                "host": "api.skyfirstlabs.com",  # platform host, no slug
                "x-tenant-slug": "gbt",
            }
        )
        ctx, bad = await _resolve_context(req)

    assert bad is None
    assert ctx.slug == "gbt"


@pytest.mark.asyncio
async def test_resolver_returns_404_marker_for_unknown_slug(
    monkeypatch, db_session
):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    clear_tenant_cache()

    async with _patch_session_local(db_session):
        req = _FakeRequest(headers={"host": "workspace-ghost.skyfirstlabs.com"})
        ctx, bad = await _resolve_context(req)

    # Spec: 404 when the caller supplied a slug that does not resolve.
    # The middleware turns ``bad`` into a JSONResponse; ``_resolve_context``
    # just signals it.
    assert bad == "ghost"
    assert ctx is DEFAULT_TENANT_CONTEXT


@pytest.mark.asyncio
async def test_resolver_returns_404_marker_for_suspended_tenant(
    monkeypatch, db_session
):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    clear_tenant_cache()

    _persist_tenant(
        db_session,
        slug="gone",
        is_active=False,
        suspended_at=datetime.now(timezone.utc),
    )
    await db_session.commit()

    async with _patch_session_local(db_session):
        req = _FakeRequest(headers={"host": "workspace-gone.skyfirstlabs.com"})
        ctx, bad = await _resolve_context(req)

    assert bad == "gone"
    assert ctx is DEFAULT_TENANT_CONTEXT


@pytest.mark.asyncio
async def test_resolver_uses_cache_on_second_call(monkeypatch, db_session):
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    clear_tenant_cache()

    _persist_tenant(db_session, slug="cachy")
    await db_session.commit()

    # First call hits DB and populates cache.
    async with _patch_session_local(db_session):
        req = _FakeRequest(headers={"host": "workspace-cachy.skyfirstlabs.com"})
        ctx1, _ = await _resolve_context(req)

    # Now ``AsyncSessionLocal`` is back to the global one. If the cache
    # works the resolver must NOT need a session — calling again with a
    # bogus session factory should still succeed.
    from src.api.middleware import tenant_resolver as tr_module

    def _exploding_factory():
        raise AssertionError("cache miss — resolver hit DB unexpectedly")

    original = tr_module.AsyncSessionLocal
    tr_module.AsyncSessionLocal = _exploding_factory
    try:
        req = _FakeRequest(headers={"host": "workspace-cachy.skyfirstlabs.com"})
        ctx2, _ = await _resolve_context(req)
    finally:
        tr_module.AsyncSessionLocal = original

    assert ctx1.slug == ctx2.slug == "cachy"


# ─── Contextvar plumbing ────────────────────────────────────────────


def test_current_tenant_default():
    assert current_tenant() is DEFAULT_TENANT_CONTEXT


def test_set_and_reset_current_tenant():
    ctx = TenantContext(
        slug="x",
        id=uuid.uuid4(),
        tier="starter",
        display_name="X",
    )
    token = set_current_tenant(ctx)
    try:
        assert current_tenant() is ctx
    finally:
        reset_current_tenant(token)

    assert current_tenant() is DEFAULT_TENANT_CONTEXT
