"""Per-tenant connection manager (Projeto A — PR #3).

Owns one ``AsyncEngine`` and one ``async_sessionmaker`` per active
tenant. Engines are created lazily on first use and cached for the
lifetime of the process; ``dispose_all()`` is called from the lifespan
shutdown hook so connections are returned cleanly.

The default tenant routes back to the existing ``engine`` /
``AsyncSessionLocal`` defined in :mod:`src.config.database`. That keeps
the single-tenant code path completely unchanged: while
``MULTI_TENANT_ENABLED`` is False every request gets the default
context, ``get_session`` returns the global pool, and nothing observes
that the manager exists.

Pool sizing follows the tier ladder from
``04-pricing-model.md`` — starter tenants get small pools, strategic
tenants get generous ones. The numbers are deliberately conservative;
PR #14 (Phase 5) raises them after we have real telemetry.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.config import database as _db_module
from src.config.settings import settings
from src.core.tenant_context import TenantContext

logger = logging.getLogger(__name__)


# ─── Pool sizing per tier ──────────────────────────────────────────
# (pool_size, max_overflow). The total ceiling per tenant is the sum.
# A starter tenant tops out at 15 simultaneous connections — comfortably
# below Postgres's default 100 even with 5 tenants on a shared pod.
TIER_POOL_SIZES = {
    "starter": (5, 10),
    "foundation": (10, 20),
    "core": (20, 40),
    "advanced": (40, 80),
    "strategic": (80, 160),
}


@dataclass(frozen=True)
class _TenantPool:
    engine: AsyncEngine
    session_maker: async_sessionmaker


class TenantConnectionManager:
    """Lazily-instantiated cache of per-tenant SQLAlchemy engines."""

    def __init__(self) -> None:
        self._pools: Dict[str, _TenantPool] = {}
        self._lock = asyncio.Lock()

    # ── Public API ─────────────────────────────────────────────

    def session_for(self, ctx: TenantContext) -> AsyncSession:
        """Return a fresh session bound to ``ctx``'s database.

        For the default context (i.e. ``MULTI_TENANT_ENABLED`` False or
        no tenant resolved) this returns a session on the global pool —
        exactly the same object the legacy ``get_db_session`` dependency
        would have produced. Callers can therefore use this even before
        the flag flip without any behaviour change.
        """
        if ctx.is_default:
            return _db_module.AsyncSessionLocal()

        # Engine creation requires the lock; reading the cached entry
        # does not. Optimistic check first.
        pool = self._pools.get(ctx.slug)
        if pool is None:
            # Synchronous lazy init — engine creation is cheap and
            # asyncio.Lock here would force every dependency to be
            # async. ``ensure_pool`` is the async-aware variant used
            # from the request dependency.
            pool = self._build_pool_sync(ctx)
            self._pools[ctx.slug] = pool
        return pool.session_maker()

    async def ensure_pool(self, ctx: TenantContext) -> None:
        """Pre-create the engine for ``ctx`` under the lock.

        Used by hot paths that want to amortise the engine-creation
        cost outside the request: warm-up at startup, scheduled
        tenant rotation, etc. ``session_for`` is safe to call without
        this; ``ensure_pool`` just guarantees no first-call latency.
        """
        if ctx.is_default or ctx.slug in self._pools:
            return
        async with self._lock:
            if ctx.slug in self._pools:
                return
            self._pools[ctx.slug] = self._build_pool_sync(ctx)

    async def dispose_all(self) -> None:
        """Close every tenant engine. Call from the FastAPI lifespan."""
        for slug, pool in list(self._pools.items()):
            try:
                await pool.engine.dispose()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "tenant_engine_dispose_failed",
                    extra={"slug": slug, "error": str(exc)},
                )
        self._pools.clear()

    def known_slugs(self) -> list[str]:
        """Slugs with a live engine in the cache. For diagnostics."""
        return list(self._pools.keys())

    # ── Internals ──────────────────────────────────────────────

    def _build_pool_sync(self, ctx: TenantContext) -> _TenantPool:
        url = self._build_url(ctx)
        pool_size, max_overflow = TIER_POOL_SIZES.get(ctx.tier, (5, 10))

        engine_kwargs: dict = {
            "echo": settings.DEBUG,
            "future": True,
        }

        if "sqlite" in url.lower():
            # SQLite cannot share an in-memory database across engines,
            # so per-tenant SQLite URLs only make sense for tests that
            # explicitly set a file path. NullPool avoids the "different
            # event loop" hazard from async_sessionmaker on SQLite.
            engine_kwargs["poolclass"] = NullPool
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            engine_kwargs.update(
                {
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_pre_ping": True,
                    "pool_recycle": 3600,
                }
            )

        engine = create_async_engine(url, **engine_kwargs)
        session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        logger.info(
            "tenant_engine_created",
            extra={
                "slug": ctx.slug,
                "tier": ctx.tier,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
            },
        )
        return _TenantPool(engine=engine, session_maker=session_maker)

    def _build_url(self, ctx: TenantContext) -> str:
        """Construct the SQLAlchemy URL for ``ctx``'s database.

        Three input modes, tried in order:

        1. ``TENANT_DB_URL_TEMPLATE`` setting — used by local dev so a
           single docker-compose Postgres can host one DB per tenant.
           The template is formatted with the registry row's fields
           (``slug``, ``db_host``, ``db_port``, ``db_name``, …).
        2. ``ctx.db_credentials_secret_arn`` pointing to an AWS Secrets
           Manager entry — production path. Looked up via boto3 and
           expected to yield a JSON blob with ``username``, ``password``
           (the URL is assembled here).
        3. Fallback to ``db_host`` + ``db_name`` with the platform's
           own credentials. Useful for dev when neither template nor
           secret ARN is set.
        """
        template = settings.TENANT_DB_URL_TEMPLATE
        if template:
            return template.format(
                slug=ctx.slug,
                db_host=ctx.db_host or settings.POSTGRES_HOST,
                db_name=ctx.db_name or ctx.slug,
                db_port=5432,
            )

        if ctx.db_credentials_secret_arn and ctx.db_credentials_secret_arn.startswith(
            "arn:aws:secretsmanager:"
        ):
            user, password = _fetch_secret(ctx.db_credentials_secret_arn)
            host = ctx.db_host or settings.POSTGRES_HOST
            return (
                f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}"
                f"@{host}:5432/{ctx.db_name}"
            )

        # Last-resort: assume the platform credentials work for the
        # tenant DB too. Local dev with shared-Postgres typically lands
        # here when the template is unset.
        host = ctx.db_host or settings.POSTGRES_HOST
        return (
            f"postgresql+asyncpg://{settings.POSTGRES_USER}:"
            f"{quote_plus(settings.POSTGRES_PASSWORD)}"
            f"@{host}:5432/{ctx.db_name or ctx.slug}"
        )


def _fetch_secret(arn: str) -> tuple[str, str]:
    """Look up an AWS Secrets Manager secret and return (user, password).

    Imported lazily so unit tests that never use a real ARN don't pay
    the boto3 import cost. Production path only — local dev sets
    ``TENANT_DB_URL_TEMPLATE`` and never reaches here.
    """
    import json

    import boto3  # type: ignore[import-untyped]

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=arn)
    blob = json.loads(response["SecretString"])
    return blob["username"], blob["password"]


# Module-level singleton — same lifetime as the FastAPI app.
tenant_connection_manager = TenantConnectionManager()


# ─── FastAPI dependency ────────────────────────────────────────────


async def get_tenant_db(request: Optional["Request"] = None):  # type: ignore[name-defined]
    """Yield an ``AsyncSession`` bound to the request's tenant.

    Drop-in replacement for ``get_db_session`` in route handlers that
    should be tenant-aware. When ``request`` is None (called from
    Celery, scripts, etc.) the contextvar populated by
    ``set_current_tenant`` is consulted instead.
    """
    from fastapi import Request  # local import for type-only use

    if request is not None and isinstance(request, Request):
        ctx: TenantContext = getattr(
            request.state, "tenant_context", None
        ) or _fallback_default()
    else:
        from src.core.tenant_context import current_tenant

        ctx = current_tenant()

    session = tenant_connection_manager.session_for(ctx)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _fallback_default() -> TenantContext:
    """Return the default tenant context — used when the middleware
    did not run (unit tests calling a handler directly)."""
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    return DEFAULT_TENANT_CONTEXT
