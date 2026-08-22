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
        # Um cliente registado cujo plano de dados não se consegue abrir não
        # deve dar 500.
        #
        # Encontrado a 15/08/2026: o cliente semente `sky` aponta para a base
        # da plataforma e o seu segredo não é legível pelo papel do `sky-be`
        # (`AccessDeniedException` no `GetSecretValue`) — de propósito, porque
        # ninguém devia resolvê-lo. Mas bastava mandar `X-Tenant-Slug: sky`,
        # sem autenticação nenhuma, para a API responder 500 com "an
        # unexpected error occurred", que não diz nada a quem o apanha. O
        # `Test connection` do Console dava uma mensagem muito melhor do que a
        # própria API.
        #
        # Passa a ser `TenantUnavailableError`, que o middleware converte na
        # MESMA resposta de "cliente não existe". Deliberado: o código já trata
        # domínio desconhecido, domínio desactivado e cliente suspenso como
        # indistinguíveis para quem sonda de fora — um cliente avariado não tem
        # de ser a excepção que confirma que ele existe. A razão a sério vai
        # para o log, e o operador tem-na no Console.
        try:
            url = self._build_url(ctx)
        except Exception as exc:  # noqa: BLE001 — qualquer falha aqui é a mesma coisa
            logger.error(
                "tenant_engine_unavailable",
                extra={
                    "slug": ctx.slug,
                    "db_name": ctx.db_name,
                    "secret_arn": ctx.db_credentials_secret_arn,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise TenantUnavailableError(ctx.slug) from exc
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


def _regiao_do_arn(arn: str) -> str | None:
    """A região de um ARN, ou `None` se aquilo não for um ARN.

    ``arn:aws:secretsmanager:eu-west-1:123456789012:secret:nome-AbCdEf``
                             ^^^^^^^^^

    Devolve `None` em vez de rebentar: o `SecretId` também aceita o NOME do
    segredo, e nesse caso não há região nenhuma para ler — quem chama cai no
    `settings.AWS_REGION`.
    """
    partes = (arn or "").split(":")
    if len(partes) > 3 and partes[0] == "arn" and partes[3]:
        return partes[3]
    return None


def _fetch_secret(arn: str) -> tuple[str, str]:
    """Look up an AWS Secrets Manager secret and return (user, password).

    Imported lazily so unit tests that never use a real ARN don't pay
    the boto3 import cost. Production path only — local dev sets
    ``TENANT_DB_URL_TEMPLATE`` and never reaches here.

    The secret payload can be either:
      * ``{"username": "...", "password": "..."}`` — historical Terraform shape
      * ``{"url": "postgresql://user:pw@host:port/db?..."}`` — what
        ``onboard-client.yml`` writes after PR #519 / Model B onboard
    """
    import json
    from urllib.parse import urlparse, unquote

    import boto3  # type: ignore[import-untyped]

    # A região SAI DO ARN.
    #
    # Isto era `boto3.client("secretsmanager")`, sem região — e o boto3, sem
    # região no ambiente, não sabe a que endpoint falar e rebenta com
    # `NoRegionError` ANTES de fazer o pedido. Nos pods da API a região vem do
    # ambiente e ninguém deu por nada; no worker do Celery não vem.
    #
    # O efeito foi grande e silencioso: o worker não conseguia ler o segredo
    # da base de NENHUM cliente, portanto não construía a ligação, portanto
    # **todas** as execuções de agentes falhavam com "data plane unavailable",
    # tentavam outra vez, e desistiam. Um agente nunca chegou a correr em
    # produção — e a app dizia à pessoa "corre em segundo plano, o que
    # encontrar aparece nos Insights".
    #
    # Tirar a região do ARN em vez do ambiente é o que a torna certa por
    # construção: o segredo VIVE na região que o próprio ARN nomeia, e isso
    # não depende de o pod ter sido configurado como deve ser. Todos os outros
    # `boto3.client` deste código já passam `region_name`; só este não passava.
    regiao = _regiao_do_arn(arn) or settings.AWS_REGION
    client = boto3.client("secretsmanager", region_name=regiao)
    response = client.get_secret_value(SecretId=arn)
    blob = json.loads(response["SecretString"])
    if "username" in blob and "password" in blob:
        return blob["username"], blob["password"]
    url = blob.get("url")
    if url:
        parsed = urlparse(url)
        if parsed.username and parsed.password is not None:
            return unquote(parsed.username), unquote(parsed.password)
    raise KeyError(
        f"tenant DB secret {arn!r} has neither "
        f"username/password nor a parseable url field"
    )


class TenantUnavailableError(RuntimeError):
    """O cliente existe, mas a sua base de dados não se consegue abrir.

    Distinto de "não existe": aquilo é uma linha que falta, isto é uma linha
    que está lá e cujo plano de dados não responde — segredo ilegível, host
    errado, base por criar. Para quem sonda de fora as duas dão a mesma
    resposta; para quem lê os logs, não.
    """

    def __init__(self, slug: str) -> None:
        super().__init__(f"tenant {slug!r} data plane unavailable")
        self.slug = slug


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
