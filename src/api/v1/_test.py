"""Smoke endpoints for Projeto A multi-tenant development.

Everything mounted under ``/api/v1/_test`` is intended for engineers
validating the platform locally — not for customer traffic. The
routes are deliberately small, side-effect-free, and return enough
information to confirm the resolver + connection manager work without
needing a real customer DB.

Two endpoints live here:

* ``GET /tenant-echo`` — return whichever tenant the middleware
  resolved for this request. Useful with a browser, ``curl``, or the
  ``end-to-end-smoke.py`` script.
* ``GET /tenant-db-ping`` — open a session through
  ``TenantConnectionManager.session_for`` and ``SELECT 1`` against
  whichever DB it routes to. Confirms the connection manager picks a
  pool without actually depending on tenant tables existing.

When ``MULTI_TENANT_ENABLED`` is False both endpoints just report the
default context — that is the entire point: the smoke runs without
needing the flag flipped.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from sqlalchemy import text

from src.config.settings import settings
from src.config.tenant_connection_manager import tenant_connection_manager
from src.core.tenant_context import DEFAULT_TENANT_CONTEXT, TenantContext

router = APIRouter()


def _ctx_from_request(request: Request) -> TenantContext:
    """Best-effort lookup of the tenant attached by the middleware.

    Falls back to the default context if the middleware did not run
    (e.g. someone called the route via a TestClient that bypasses
    middleware) — that way the endpoint never 500s in tests.
    """
    return getattr(request.state, "tenant_context", DEFAULT_TENANT_CONTEXT)


def _ctx_payload(ctx: TenantContext) -> Dict[str, Any]:
    return {
        "slug": ctx.slug,
        "id": str(ctx.id),
        "tier": ctx.tier,
        "display_name": ctx.display_name,
        "is_default": ctx.is_default,
        "is_active": ctx.is_active,
        "rate_limit_rpm": ctx.rate_limit_rpm,
        "rate_limit_tpm": ctx.rate_limit_tpm,
        # Routing surfaces — useful when debugging local docker setups.
        "db_host": ctx.db_host,
        "db_name": ctx.db_name,
        "redis_host": ctx.redis_host,
        "bedrock_inference_profile_arn": ctx.bedrock_inference_profile_arn,
        # Don't echo the Secrets Manager ARNs in plain text — even in a
        # smoke endpoint, leaking those by default invites bad habits.
        "has_db_credentials_secret": bool(ctx.db_credentials_secret_arn),
        "has_redis_credentials_secret": bool(ctx.redis_credentials_secret_arn),
        "feature_flags": ctx.feature_flags,
        "capacity_limits": ctx.capacity_limits,
    }


@router.get(
    "/tenant-echo",
    summary="Echo the tenant resolved for this request",
    description=(
        "Returns the TenantContext attached by the resolver middleware. "
        "While MULTI_TENANT_ENABLED is False every request gets the "
        "default context — the slug field will read 'default'."
    ),
)
async def tenant_echo(request: Request) -> Dict[str, Any]:
    ctx = _ctx_from_request(request)
    return {
        "multi_tenant_enabled": settings.MULTI_TENANT_ENABLED,
        "tenant": _ctx_payload(ctx),
        "resolved_from": _resolution_signal(request, ctx),
    }


@router.get(
    "/tenant-db-ping",
    summary="Open a tenant-scoped session and SELECT 1",
    description=(
        "Routes through TenantConnectionManager.session_for. Returns "
        "the resolved tenant + whichever pool was picked. Does not "
        "depend on any tenant-specific table existing."
    ),
)
async def tenant_db_ping(request: Request) -> Dict[str, Any]:
    ctx = _ctx_from_request(request)
    session = tenant_connection_manager.session_for(ctx)
    try:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar_one()
    finally:
        await session.close()

    return {
        "tenant_slug": ctx.slug,
        "pool": "global" if ctx.is_default else f"tenant:{ctx.slug}",
        "select_1": value,
        "known_tenant_pools": tenant_connection_manager.known_slugs(),
    }


def _resolution_signal(request: Request, ctx: TenantContext) -> str:
    """Best-guess label for *how* the tenant was resolved.

    Looks at the same precedence order the middleware uses. Purely
    informational — useful when running curl against a local stack to
    confirm e.g. that the X-Tenant-Slug header took priority over the
    Host header (or vice versa, when debugging staging traffic).
    """
    if ctx.is_default:
        return "default" if not settings.MULTI_TENANT_ENABLED else "fallback"

    host = request.headers.get("host", "")
    if "workspace-" in host or "api-" in host:
        return "subdomain"
    if request.headers.get("x-tenant-slug"):
        return "header"
    if request.headers.get("authorization", "").startswith("Bearer "):
        return "jwt"
    return "unknown"
