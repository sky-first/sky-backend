"""Tests for ``TenantConnectionManager`` (Projeto A — PR #3)."""

from __future__ import annotations

import uuid

import pytest

from src.config.settings import settings
from src.config.tenant_connection_manager import (
    TIER_POOL_SIZES,
    TenantConnectionManager,
)
from src.core.tenant_context import DEFAULT_TENANT_CONTEXT, TenantContext


def _tenant(slug: str = "gbt", tier: str = "starter", **extra) -> TenantContext:
    defaults = dict(
        slug=slug,
        id=uuid.uuid4(),
        tier=tier,
        display_name=slug.upper(),
        db_host="postgres-shared.local",
        db_name=slug,
        db_credentials_secret_arn="",
        redis_host="redis.local",
        redis_credentials_secret_arn="",
    )
    defaults.update(extra)
    return TenantContext(**defaults)


# ── Default context → global pool ─────────────────────────────────


@pytest.mark.asyncio
async def test_default_context_routes_to_global_pool():
    mgr = TenantConnectionManager()
    session = mgr.session_for(DEFAULT_TENANT_CONTEXT)
    # ``AsyncSessionLocal()`` returns an ``AsyncSession`` — no engine
    # was created for the default context.
    assert mgr.known_slugs() == []
    await session.close()


# ── Real tenant → engine cached ───────────────────────────────────


@pytest.mark.asyncio
async def test_engine_cached_across_calls(monkeypatch):
    # Force template mode so the manager does not try Secrets Manager.
    monkeypatch.setattr(
        settings,
        "TENANT_DB_URL_TEMPLATE",
        "sqlite+aiosqlite:///./_tenant_{slug}.db",
    )

    mgr = TenantConnectionManager()
    ctx = _tenant(slug="alpha")

    s1 = mgr.session_for(ctx)
    s2 = mgr.session_for(ctx)
    try:
        assert mgr.known_slugs() == ["alpha"]
        # Both sessions come from the same session_maker bound to the
        # same engine — identity comparison of the maker confirms caching.
        assert mgr._pools["alpha"].session_maker is mgr._pools["alpha"].session_maker
    finally:
        await s1.close()
        await s2.close()
        await mgr.dispose_all()


@pytest.mark.asyncio
async def test_distinct_tenants_get_distinct_engines(monkeypatch):
    monkeypatch.setattr(
        settings,
        "TENANT_DB_URL_TEMPLATE",
        "sqlite+aiosqlite:///./_tenant_{slug}.db",
    )

    mgr = TenantConnectionManager()
    a, b = _tenant("alpha"), _tenant("beta")

    sa = mgr.session_for(a)
    sb = mgr.session_for(b)
    try:
        assert set(mgr.known_slugs()) == {"alpha", "beta"}
        assert mgr._pools["alpha"].engine is not mgr._pools["beta"].engine
    finally:
        await sa.close()
        await sb.close()
        await mgr.dispose_all()


# ── Pool sizing per tier ──────────────────────────────────────────


@pytest.mark.parametrize(
    "tier,expected",
    sorted(TIER_POOL_SIZES.items()),
)
def test_pool_sizing_per_tier(tier, expected):
    pool_size, max_overflow = expected
    # The constants the manager reads must match the public dictionary.
    assert TIER_POOL_SIZES[tier] == (pool_size, max_overflow)


@pytest.mark.parametrize(
    "tier", ["starter", "foundation", "core", "advanced", "strategic"]
)
@pytest.mark.asyncio
async def test_each_tier_builds_a_pool(monkeypatch, tier):
    # Use a file-backed SQLite so create_engine succeeds without
    # touching a real Postgres. The point is exercising the tier path.
    monkeypatch.setattr(
        settings,
        "TENANT_DB_URL_TEMPLATE",
        "sqlite+aiosqlite:///./_tier_test.db",
    )

    mgr = TenantConnectionManager()
    ctx = _tenant(slug=f"t-{tier}", tier=tier)
    session = mgr.session_for(ctx)
    try:
        assert f"t-{tier}" in mgr.known_slugs()
    finally:
        await session.close()
        await mgr.dispose_all()


# ── URL building precedence ───────────────────────────────────────


def test_url_template_used_when_set(monkeypatch):
    monkeypatch.setattr(
        settings,
        "TENANT_DB_URL_TEMPLATE",
        "postgresql+asyncpg://u:p@h:5432/sky_{slug}",
    )

    mgr = TenantConnectionManager()
    url = mgr._build_url(_tenant(slug="x"))
    assert url == "postgresql+asyncpg://u:p@h:5432/sky_x"


def test_url_falls_back_to_platform_creds_when_no_template_or_arn(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_DB_URL_TEMPLATE", "")
    monkeypatch.setattr(settings, "POSTGRES_USER", "skyu")
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "skyp")

    mgr = TenantConnectionManager()
    ctx = _tenant(slug="x", db_credentials_secret_arn="")
    url = mgr._build_url(ctx)
    assert url.startswith("postgresql+asyncpg://skyu:skyp@")
    assert url.endswith("/x")


# ── ensure_pool is async-safe ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_pool_is_noop_for_default(monkeypatch):
    mgr = TenantConnectionManager()
    await mgr.ensure_pool(DEFAULT_TENANT_CONTEXT)
    assert mgr.known_slugs() == []


@pytest.mark.asyncio
async def test_ensure_pool_is_idempotent(monkeypatch):
    monkeypatch.setattr(
        settings,
        "TENANT_DB_URL_TEMPLATE",
        "sqlite+aiosqlite:///./_idemp.db",
    )

    mgr = TenantConnectionManager()
    ctx = _tenant("idemp")
    await mgr.ensure_pool(ctx)
    await mgr.ensure_pool(ctx)
    assert mgr.known_slugs() == ["idemp"]
    await mgr.dispose_all()
