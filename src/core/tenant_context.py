"""Tenant context — the per-request handle for Model B multi-tenancy.

A ``TenantContext`` is the small, immutable bundle of identity + routing
data the rest of the codebase needs in order to act on behalf of one
tenant: the slug (URL/secret-path identifier), the registry row id,
the tier, the DB/Redis hosts, the Bedrock inference profile ARN.

While ``settings.MULTI_TENANT_ENABLED`` is False the platform serves
exactly one logical tenant and every request gets ``DEFAULT_TENANT_CONTEXT``
attached. Code that wants to be multi-tenant ready today can already
read ``request.state.tenant_context`` (or the contextvar) without
caring whether the flag is on or off — the value is always populated.

The contextvar is for paths where ``request`` is not in scope: Celery
tasks, background workers, repositories spawned from a worker. Anyone
manipulating it directly must remember to ``.reset(token)`` to avoid
leaking tenant context across requests served on the same asyncio task.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional
from uuid import UUID

# UUID(int=0) — the sentinel "no tenant" id used by DEFAULT_TENANT_CONTEXT.
# Real tenants always have a random UUIDv4 written by the registry table.
_NIL_UUID = UUID(int=0)


@dataclass(frozen=True)
class TenantContext:
    """Immutable per-request tenant handle.

    Frozen so a handler that copies the context (e.g. to pass into a
    Celery task) cannot accidentally mutate it for the caller. Use
    :func:`dataclasses.replace` to produce a tweaked copy.
    """

    slug: str
    id: UUID
    tier: str
    display_name: str

    # Data plane — populated for real tenants, empty strings for the
    # default context (the default tenant routes to the global pool).
    db_host: str = ""
    db_name: str = ""
    db_credentials_secret_arn: str = ""
    redis_host: str = ""
    redis_credentials_secret_arn: str = ""

    # Optional per-tenant Bedrock cost tracking
    bedrock_inference_profile_arn: Optional[str] = None

    # Rate limiting ceilings (per-tenant)
    rate_limit_rpm: int = 60
    rate_limit_tpm: int = 50_000

    # Lifecycle
    is_active: bool = True

    # Capability + capacity surfaces — kept as plain dicts here; the
    # service layer can validate against the Pydantic schema if needed.
    feature_flags: Dict[str, Any] = field(default_factory=dict)
    capacity_limits: Dict[str, int] = field(
        default_factory=lambda: {"agents": 0, "sources": 0, "indexed_gb": 0}
    )

    # Per-tenant /login surface (Model B). The resolver middleware
    # copies this from the registry row so /api/v1/auth/methods does
    # not have to re-query the platform DB on every login page hit.
    auth_methods: Dict[str, bool] = field(default_factory=dict)
    sso_provider: str = ""

    @property
    def is_default(self) -> bool:
        """True iff this is the platform-wide default context.

        Repositories and the connection manager use this to short-circuit
        the per-tenant routing path back to the global pool — which is
        what every request hits while ``MULTI_TENANT_ENABLED`` is False.
        """
        return self.id == _NIL_UUID

    def with_overrides(self, **changes: Any) -> "TenantContext":
        """Return a copy with the given fields replaced.

        Convenience wrapper around ``dataclasses.replace`` — Celery tasks
        sometimes need to take the resolved tenant and bump one field
        (e.g. swap ``rate_limit_rpm`` for a worker-side override).
        """
        return replace(self, **changes)


# ─── Default tenant ────────────────────────────────────────────────
# The slug ``"default"`` is reserved — the migration's regex check
# allows it (``^[a-z0-9-]{2,50}$``) but the registry seeding never
# creates a row for it. Code that needs to refuse routing to the
# default tenant (e.g. once ``MULTI_TENANT_ENABLED`` is True everywhere)
# should check ``ctx.is_default`` explicitly.

DEFAULT_TENANT_CONTEXT = TenantContext(
    slug="default",
    id=_NIL_UUID,
    tier="starter",  # arbitrary but valid per the tier CHECK constraint
    display_name="Default (single-tenant mode)",
)


# ─── Per-task contextvar ───────────────────────────────────────────
# ASGI runs each request on its own asyncio task, so a ContextVar
# transparently scopes to that request without us threading the value
# manually. Celery tasks (and other non-request entry points) must set
# this themselves before doing tenant-scoped work.

_current_tenant: ContextVar[TenantContext] = ContextVar(
    "skyfirst_current_tenant", default=DEFAULT_TENANT_CONTEXT
)


def current_tenant() -> TenantContext:
    """Return the tenant for the current asyncio task.

    Falls back to :data:`DEFAULT_TENANT_CONTEXT` when nothing has set
    the contextvar — i.e. when ``MULTI_TENANT_ENABLED`` is False or the
    caller is on a code path that never went through the middleware
    (script entry points, alembic, the test suite outside of a route).
    """
    return _current_tenant.get()


def set_current_tenant(ctx: TenantContext):
    """Set the contextvar and return a reset token.

    The caller MUST hold the token and call ``_current_tenant.reset(token)``
    when done — otherwise the value leaks into whatever the asyncio task
    handles next. The middleware wraps this in a try/finally; direct
    callers (Celery's ``before_task_publish`` signal handler, the
    smoke-test fixture, …) must mirror that pattern.
    """
    return _current_tenant.set(ctx)


def reset_current_tenant(token) -> None:
    """Reset the contextvar to its previous value.

    Thin wrapper so callers do not need to import the private name.
    """
    _current_tenant.reset(token)
