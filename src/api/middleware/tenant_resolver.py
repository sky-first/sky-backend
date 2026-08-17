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
from sqlalchemy import or_, select

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


# Map host → (context | None, expires_at). Guarda também as respostas
# negativas: a plataforma serve os seus próprios hosts (``app.``,
# ``console.``, ``grafana-prd.``) em cada pedido, e sem cachear o "não é
# de ninguém" cada um deles pagava uma ida à base de dados.
_HOST_CACHE: Dict[str, Tuple[Optional[TenantContext], float]] = {}
_MISS = object()


def _host_cache_get(host: str) -> object:
    entry = _HOST_CACHE.get(host)
    if entry is None:
        return _MISS
    ctx, expires_at = entry
    if expires_at < time.monotonic():
        _HOST_CACHE.pop(host, None)
        return _MISS
    return ctx


def _host_cache_put(host: str, ctx: Optional[TenantContext]) -> None:
    _HOST_CACHE[host] = (ctx, time.monotonic() + _CACHE_TTL_SECONDS)


def clear_tenant_cache() -> None:
    """Reset the resolver cache.

    Exposed for tests and for the Internal Console: when an operator
    updates a row in ``tenant_registry`` (e.g. flips ``is_active``) the
    middleware needs to see the change immediately rather than after the
    60s TTL. The console calls this on every mutation.
    """
    _REGISTRY_CACHE.clear()
    _HOST_CACHE.clear()


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

# Nomes que parecem de cliente mas são hosts NOSSOS.
#
# Duas funções, e a segunda só passou a existir com a resolução por host:
#
#  1. o resolvedor não lê `sky-stg.<base>` como `slug=sky`, o que daria 404
#     a todos os pedidos de quem ainda não entrou;
#  2. `console_service.create_tenant` RECUSA estes slugs. Sem isso, criar um
#     cliente chamado `app` faria `app.skyfirstlabs.com` — o endereço
#     principal do produto — passar a servir esse cliente.
#
# O comentário anterior dizia que "o workflow onboard-client recusa estes
# slugs ao criar". Não recusa: a lista dele são nomes de namespaces do
# Kubernetes (`argocd`, `kube-system`, `default`, `staging`, `production`,
# …) e não inclui nenhum destes. A regra é imposta aqui e no serviço.
#
# `app` entrou em 16/08 com `app.skyfirstlabs.com`. Regra para quem
# acrescentar hosts: **um host novo em `<nome>.skyfirstlabs.com` tem de
# entrar nesta lista no mesmo PR**, senão fica à mercê do próximo cliente
# com esse nome.
_RESERVED_SLUGS: frozenset[str] = frozenset(
    {"sky", "app", "platform", "console", "demo", "api", "www", "admin", "auth"}
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
    slug = m.group(1) or m.group(2)
    if slug in _RESERVED_SLUGS:
        return None
    return slug


def _normalise_host(host_header: Optional[str]) -> Optional[str]:
    """``Example.COM:8443`` → ``example.com``. ``None`` quando não há host."""
    if not host_header:
        return None
    host = host_header.split(":", 1)[0].strip().lower().rstrip(".")
    return host or None


def rotulo_candidato_a_slug(host: str) -> Optional[str]:
    """O primeiro rótulo de ``host``, se puder representar um cliente.

    Duas condições, e as duas existem por um motivo concreto:

    * **Não pode ser um nome reservado.** ``sky`` tem linha no registo e
      aponta para a base da plataforma; ``console``, ``api``, ``demo`` são
      hosts nossos. Nenhum deles pode ser lido como cliente.
    * **O resto do host tem de ser um domínio nosso.** Sem isto, bastava
      apontar ``gbt.dominio-qualquer.com`` ao nosso balanceador para ser
      servido como a GBT — o host é escolhido por quem faz o pedido.

    Público de propósito: é a regra que decide se o slug entra sequer na
    consulta, e um teste que a contorne não está a testar nada.
    """
    rotulo, _, resto = host.partition(".")
    if not rotulo or rotulo in _RESERVED_SLUGS or not resto:
        return None
    for base in settings.tenant_base_domains():
        if resto == base or resto.endswith("." + base):
            return rotulo
    return None


async def _tenant_from_host_registry(host_header: Optional[str]) -> Optional[TenantContext]:
    """Resolve um host **perguntando ao registo**, em vez de o adivinhar.

    Cobre as duas formas que o regex de sub-domínio nunca soube ler:

    * ``<slug>.skyfirstlabs.com`` — o endereço que o pipeline de
      provisionamento cria para cada cliente e que a aplicação ignorava.
      Estava a emitir DNS e certificados para portas que não abriam.
    * ``custom_domain`` — a coluna existe desde o início, a Console grava-a,
      e ninguém alguma vez a leu. Um cliente que peça ``sky.empresa.com``
      passa a ser servido.

    **Porque é uma consulta e não uma expressão regular.** Alargar o regex
    para aceitar ``<label>.<base>`` era a mudança óbvia — e partia produção.
    Um host sem linha no registo passaria a produzir um slug, e um slug que
    não resolve é um 404: ``grafana-prd``, ``auth-prd``, ``app`` deixariam
    de responder a quem ainda não entrou. Confirmando contra o registo, um
    host desconhecido devolve ``None`` e o pedido segue para o contexto da
    plataforma, que é exactamente o que esses hosts precisam.

    O rótulo só é aceite quando o resto do host é um domínio nosso. Sem
    isso, ``gbt.dominio-de-terceiros.com`` apontado ao nosso ingress
    escolhia o cliente que quisesse.
    """
    host = _normalise_host(host_header)
    if not host or "." not in host:
        return None

    cached = _host_cache_get(host)
    if cached is not _MISS:
        return cast(Optional[TenantContext], cached)

    condicoes = [Tenant.custom_domain == host]
    rotulo = rotulo_candidato_a_slug(host)
    if rotulo:
        condicoes.append(Tenant.slug == rotulo)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tenant).where(or_(*condicoes)))
            linhas = list(result.scalars().all())
    except Exception as exc:  # noqa: BLE001
        # Uma falha de leitura não pode transformar-se em 404. Não se
        # cacheia o erro: o próximo pedido tenta outra vez.
        logger.warning(
            "tenant_resolver_host_lookup_failed",
            extra={"host": host, "error": str(exc)},
        )
        return None

    # Um domínio próprio é mais explícito do que um rótulo que calha bater
    # certo com um slug — se ambos existirem, ganha o domínio próprio.
    linhas.sort(key=lambda r: 0 if (r.custom_domain or "").lower() == host else 1)
    escolhida = next((r for r in linhas if r.is_active), None)

    ctx = _row_to_context(escolhida) if escolhida is not None else None
    _host_cache_put(host, ctx)
    if ctx is not None:
        _cache_put(ctx)
    return ctx


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
    return _row_to_context(row)


def _row_to_context(row: Tenant) -> TenantContext:
    """Inflate a ``tenant_registry`` row into a :class:`TenantContext`.

    Shared by the slug loader (web path) and the id loader (device path) so
    both produce byte-identical contexts.
    """
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
        auth_methods=dict(row.auth_methods or {}),
        sso_provider=row.sso_provider or "",
        logo_url=row.logo_url or "",
    )


def _tid_from_jwt(auth_header: Optional[str]) -> Optional[str]:
    """Read the signed ``tid`` (tenant UUID) claim from a Bearer token.

    The device (mobile) path: a phone hits the bare ``api.`` host with no
    sub-domain, so the tenant travels inside the JWT. The claim is signed —
    a tampered token fails ``verify_token`` (401) long before this is called.
    """
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
    tid = payload.get("tid")
    return tid if isinstance(tid, str) else None


async def _load_tenant_by_id(tenant_id: str) -> Optional[TenantContext]:
    """Registry lookup keyed on the tenant UUID (device path).

    Mirrors :func:`_load_tenant_from_db` but resolves the ``tid`` a mobile
    token carries instead of a slug. Returns ``None`` for an unknown,
    suspended, or malformed id.
    """
    import uuid as _uuid

    try:
        tid = _uuid.UUID(str(tenant_id))
    except (ValueError, TypeError):
        return None
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Tenant).where(Tenant.id == tid))
            row: Optional[Tenant] = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tenant_resolver_registry_query_by_id_failed",
            extra={"tid": str(tenant_id), "error": str(exc)},
        )
        return None
    if row is None or not row.is_active:
        return None
    return _row_to_context(row)


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

    # 2. O host, confirmado contra o registo, ganha a tudo o resto.
    #
    # Quem escreve `gbt.skyfirstlabs.com` na barra de endereço está a dizer
    # a que cliente quer ir, e isso é mais explícito do que um token que
    # calhou ficar no browser de outra sessão. Vem à frente do `or` abaixo
    # de propósito: um token do cliente A não deve continuar a servir
    # páginas quando o endereço é o do cliente B.
    #
    # Um host que não seja de ninguém devolve `None` e não interrompe nada
    # — a cadeia normal corre a seguir, como sempre correu.
    ctx_por_host = await _tenant_from_host_registry(request.headers.get("host"))
    if ctx_por_host is not None:
        return ctx_por_host, None

    # 3. Pick the slug from the request, in priority order.
    slug = (
        _slug_from_host(request.headers.get("host"))
        or request.headers.get("x-tenant-slug")
        or _slug_from_jwt(request.headers.get("authorization"))
    )

    if not slug:
        # Device (mobile) path: no sub-domain, so resolve from the signed
        # ``tid`` claim in the JWT — this is what lets a phone hitting the
        # bare ``api.`` host route to the right tenant. (BE-01)
        tid = _tid_from_jwt(request.headers.get("authorization"))
        if tid:
            ctx = await _load_tenant_by_id(tid)
            if ctx is not None:
                _cache_put(ctx)
                return ctx, None
            # A signed tid that no longer maps to an active tenant → 404,
            # never the default tenant.
            return DEFAULT_TENANT_CONTEXT, f"tid:{tid}"
        # No sub-domain and no tid → default context (rate-limiting still
        # works via its own ceilings). Strict 400 rejection + membership 403
        # for authenticated device requests is enforced at the auth layer via
        # ``src.core.device_tenant.resolve_device_tenant``.
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
