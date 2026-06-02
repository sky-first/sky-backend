"""Tenant resolver middleware.

Sits between auth and rate-limit in the middleware stack. For every
HTTP request it answers the question "which tenant is this?" and
attaches the answer to ``request.state.tenant_context`` and to the
``_current_tenant`` contextvar in :mod:`src.core.tenant_context`.

Resolution order:

1. ``MULTI_TENANT_ENABLED`` flag — when OFF the middleware always
   attaches :data:`DEFAULT_TENANT_CONTEXT` and returns immediately.
   This is the shipping behaviour throughout Phase 1-4 of Projeto A.
2. Subdomain — ``workspace-{slug}.<base>`` or ``api-{slug}.<base>``
   (and the staging variants ``workspace-{slug}-stg.<base>``,
   ``api-{slug}-stg.<base>``).
3. Explicit ``X-Tenant-Slug`` header — useful for tests and for the
   Internal Console which talks to the platform's own hostname.
4. ``tenant_slug`` claim in the JWT — fallback for clients that hit
   the bare ``api.skyfirstlabs.com`` host (rare).

When the flag is ON but the slug fails to resolve to an active row in
the registry, the middleware returns ``404`` immediately — this is the
behaviour spec'd in ``02-tenant-implementation-spec.md`` section 3.1.
While the flag is OFF an unresolvable host is benign and falls back
to the default context.

In-memory cache (``_REGISTRY_CACHE``) is a simple TTL dict keyed on
slug. PR #3 (``TenantConnectionManager``) replaces it with a proper
LRU bounded by tier count.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, Dict, Optional, Tuple, cast

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError
from sqlalchemy import select

from src.config.database import AsyncSessionLocal
from src.config.settings import settings
from src.core.security import verify_token
from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)
from src.models.tenant import Tenant

logger = logging.getLogger(__name__)


# ─── Cache ─────────────────────────────────────────────────────────
# Map slug → (context, monotonic_expires_at). 60s TTL is short enough
# that suspending a tenant takes effect quickly and long enough to
# absorb the per-request lookup load on a hot path.
_CACHE_TTL_SECONDS = 60.0
_REGISTRY_CACHE: Dict[str, Tuple[TenantContext, float]] = {}


def _cache_get(slug: str) -> Optional[TenantContext]:
    entry = _REGISTRY_CACHE.get(slug)
    if entry is None:
        return None
    ctx, expires_at = entry
    if expires_at < time.monotonic():
        _REGISTRY_CACHE.pop(slug, None)
        return None
    return ctx


def _cache_put(ctx: TenantContext) -> None:
    _REGISTRY_CACHE[ctx.slug] = (ctx, time.monotonic() + _CACHE_TTL_SECONDS)


def clear_tenant_cache() -> None:
    """Reset the resolver cache.

    Exposed for tests and for the Internal Console: when an operator
    updates a row in ``tenant_registry`` (e.g. flips ``is_active``) the
    middleware needs to see the change immediately rather than after the
    60s TTL. The console calls this on every mutation.
    """
    _REGISTRY_CACHE.clear()


# ─── Subdomain parsing ─────────────────────────────────────────────
# Accepts these patterns (kept in sync with auth.py's
# ``_AUTH_SUBDOMAIN_RE``):
#
#   workspace-<slug>.<base>       (production explicit prefix)
#   workspace-<slug>-stg.<base>   (staging explicit prefix)
#   api-<slug>.<base>             (production API subdomain)
#   api-<slug>-stg.<base>         (staging API subdomain)
#   <slug>-stg.<base>             (legacy bare slug, staging only)
#
# Rule: a host resolves to a tenant when it has a ``workspace-``/``api-``
# prefix (with or without the ``-stg`` staging suffix) OR a bare
# ``<slug>-stg`` form. A bare host with neither (``demo.<base>``,
# ``api.<base>``, ``<base>``) is NOT a tenant. ``sky-stg.<base>`` is the
# platform default and never matches in practice: the onboard-client
# workflow's reserved-name list refuses ``sky`` as a tenant slug.
_SUBDOMAIN_RE = re.compile(
    r"^(?:(?:workspace|api)-([a-z0-9-]{2,50}?)(?:-stg)?|([a-z0-9-]{2,50}?)-stg)\."
)


def _slug_from_host(host_header: Optional[str]) -> Optional[str]:
    if not host_header:
        return None
    # Strip an optional ``:port`` suffix before matching.
    host = host_header.split(":", 1)[0].lower()
    m = _SUBDOMAIN_RE.match(host)
    if not m:
        return None
    # Group 1 = prefixed form (workspace-/api-), group 2 = bare -stg form.
    return m.group(1) or m.group(2)


def _slug_from_jwt(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        payload = verify_token(auth_header[len("Bearer ") :])
    except JWTError:
        return None
    except Exception:  # noqa: BLE001 — verify_token wraps several errors
        return None
    if not isinstance(payload, dict):
        return None
    slug = payload.get("tenant_slug")
    return slug if isinstance(slug, str) else None


# ─── Registry lookup ───────────────────────────────────────────────
async def _load_tenant_from_db(slug: str) -> Optional[TenantContext]:
    """Read a single registry row and inflate it into a TenantContext.

    Returns ``None`` if the row does not exist, is suspended, OR the
    registry query fails (table missing in tests, transient DB error
    in prod, …). The middleware caller turns any of those into a 404,
    which is the correct behaviour from the client's perspective:
    "this tenant is not currently available".
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tenant).where(Tenant.slug == slug))
            row: Optional[Tenant] = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tenant_resolver_registry_query_failed",
            extra={"slug": slug, "error": str(exc)},
        )
        return None

    if row is None:
        return None
    if not row.is_active:
        return None
    return TenantContext(
        slug=row.slug,
        id=row.id,
        tier=row.tier,
        display_name=row.display_name,
        db_host=row.db_host,
        db_name=row.db_name,
        db_credentials_secret_arn=row.db_credentials_secret_arn,
        redis_host=row.redis_host,
        redis_credentials_secret_arn=row.redis_credentials_secret_arn,
        bedrock_inference_profile_arn=row.bedrock_inference_profile_arn,
        rate_limit_rpm=row.rate_limit_rpm,
        rate_limit_tpm=row.rate_limit_tpm,
        is_active=row.is_active,
        feature_flags=dict(row.feature_flags or {}),
        capacity_limits=dict(row.capacity_limits or {}),
    )


async def _resolve_context(request: Request) -> Tuple[TenantContext, Optional[str]]:
    """Resolve the tenant for ``request``.

    Returns a tuple of (context, error_slug). When the flag is OFF, or
    when no slug is supplied at all, returns the default context and a
    ``None`` error_slug — i.e. the request proceeds with default routing.
    When a slug IS supplied but does not match an active row, the second
    tuple element is set to that slug so the caller can produce a 404
    that identifies the bad input.
    """
    # 1. Flag OFF — single-tenant mode. Default context for every request.
    if not settings.MULTI_TENANT_ENABLED:
        return DEFAULT_TENANT_CONTEXT, None

    # 2. Pick the slug from the request, in priority order.
    slug = (
        _slug_from_host(request.headers.get("host"))
        or request.headers.get("x-tenant-slug")
        or _slug_from_jwt(request.headers.get("authorization"))
    )

    if not slug:
        # No slug at all → fall back to default; rate-limiting still works
        # because the default context has its own ceilings.
        return DEFAULT_TENANT_CONTEXT, None

    slug = slug.strip().lower()

    # 3. Cache hit?
    cached = _cache_get(slug)
    if cached is not None:
        return cached, None

    # 4. Load from registry.
    ctx = await _load_tenant_from_db(slug)
    if ctx is None:
        return DEFAULT_TENANT_CONTEXT, slug

    _cache_put(ctx)
    return ctx, None


# ─── Middleware ────────────────────────────────────────────────────
# Public path list — these never go through registry lookup. Health
# probes and OPTIONS preflights are the obvious cases; we also keep
# /docs and /metrics open so the platform stays observable even if the
# DB is misbehaving.
_PUBLIC_PATHS: tuple = (
    "/health",
    "/healthz",
    "/healthz/ready",
    "/healthz/live",
    "/ready",
    "/live",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
)


async def tenant_resolver_middleware(request: Request, call_next: Callable) -> Response:
    """ASGI middleware that attaches a :class:`TenantContext` to every request.

    Order in the stack (set in ``src/main.py``):

    * runs AFTER auth (so JWT fallback can read ``Authorization``)
    * runs BEFORE rate-limit (so rate-limit can scope per-tenant)
    """
    # Preflight requests must not be blocked — CORS handles them.
    if request.method == "OPTIONS":
        return cast(Response, await call_next(request))

    # Health probes and docs paths never resolve a tenant.
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/static/"):
        request.state.tenant_context = DEFAULT_TENANT_CONTEXT
        return cast(Response, await call_next(request))

    ctx, bad_slug = await _resolve_context(request)

    if bad_slug is not None:
        # Flag is ON, caller did supply a slug, but it does not match
        # any active row. 404 is correct per the spec — tenant does not
        # exist or is suspended.
        logger.warning(
            "tenant_resolver_unknown_slug",
            extra={"slug": bad_slug, "path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "tenant_not_found",
                "detail": ("The requested tenant does not exist or is suspended."),
            },
        )

    request.state.tenant_context = ctx
    token = set_current_tenant(ctx)
    try:
        response = await call_next(request)
    finally:
        reset_current_tenant(token)
    return response
