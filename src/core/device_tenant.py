"""Device (mobile) tenant resolution — BE-01.

Web clients resolve their tenant from the request sub-domain
(``workspace-<slug>.skyfirstlabs.com``). A mobile app hits the bare
``api.skyfirstlabs.com`` host with no sub-domain, so it carries a **signed,
immutable ``tid``** (tenant UUID) plus a ``tslug`` claim inside its JWT.

This module is the single, dependency-injected place that turns a token's
claims into either a resolved tenant *or* an explicit rejection. The registry
lookup and the membership check are injected as plain callables so the policy
is free of any DB / framework import and is trivially unit-testable.

Policy — evaluated in order:

  1. no ``tid`` claim               → UNRESOLVED  → caller returns **400**
  2. ``tid`` is not an active tenant → UNRESOLVED  → caller returns **400**
  3. user is not a member of ``tid`` → FORBIDDEN   → caller returns **403**
  4. otherwise                       → RESOLVED(context)

The ``tid`` is only a *hint of identity*, never an *authorization*. Even a
validly-signed token is re-checked against live membership (step 3), so an
off-boarded user loses access the moment their membership row disappears —
not when the token eventually expires. This is the core guarantee behind
test T-01.8.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

# The claim names carried in every mobile-issued token.
TENANT_CLAIM = "tid"
TENANT_SLUG_CLAIM = "tslug"


class DeviceResolution(str, Enum):
    """Outcome of resolving a device request's tenant."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"  # no / unknown tenant → HTTP 400 (never default)
    FORBIDDEN = "forbidden"  # valid tenant, user is not a member → HTTP 403


@dataclass(frozen=True)
class DeviceTenantResult:
    resolution: DeviceResolution
    context: Optional[Any] = None
    tid: Optional[str] = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.resolution is DeviceResolution.RESOLVED


# ─── Token claim helpers ────────────────────────────────────────────────────


def tenant_claims_for_context(ctx: Any) -> Dict[str, str]:
    """The claims a login/refresh must sign into a token for ``ctx``.

    Returns an empty dict for the default (single-tenant) context so tokens
    minted while ``MULTI_TENANT_ENABLED`` is off stay exactly as they are
    today — this makes the change a strict no-op in single-tenant mode.
    """
    if ctx is None or getattr(ctx, "is_default", False):
        return {}
    return {TENANT_CLAIM: str(ctx.id), TENANT_SLUG_CLAIM: ctx.slug}


def carry_tenant_claims(payload: Dict[str, Any]) -> Dict[str, str]:
    """Extract the tenant claims from a token payload so a **refresh preserves
    the tid** (test T-01.7).

    Switching tenants must always be an *explicit* re-issue
    (``/auth/select-workspace``), never a side effect of refreshing — so we
    only ever carry the existing tenant forward here, never change it.
    """
    carried: Dict[str, str] = {}
    tid = payload.get(TENANT_CLAIM)
    if tid:
        carried[TENANT_CLAIM] = str(tid)
    tslug = payload.get(TENANT_SLUG_CLAIM)
    if tslug:
        carried[TENANT_SLUG_CLAIM] = str(tslug)
    return carried


# ─── Resolution policy ──────────────────────────────────────────────────────


async def resolve_device_tenant(
    claims: Dict[str, Any],
    *,
    load_tenant_by_id: Callable[[str], Awaitable[Optional[Any]]],
    is_member: Callable[[str, str], Awaitable[bool]],
) -> DeviceTenantResult:
    """Resolve the tenant for a device request from its verified token claims.

    ``claims`` is the already-verified JWT payload (signature checked upstream
    by ``verify_token`` — tampering therefore never reaches here; it fails as a
    401 before this is called, which is test T-01.3).

    ``load_tenant_by_id(tid)`` returns an active tenant context or ``None``.
    ``is_member(user_id, tid)`` is the live membership check.
    """
    tid = claims.get(TENANT_CLAIM)
    user_id = claims.get("sub")

    # 1. No tenant claim at all → never fall back to a default tenant.
    if not tid:
        return DeviceTenantResult(DeviceResolution.UNRESOLVED, reason="no_tid_claim")

    tid = str(tid)

    # 2. The tenant must exist and be active in the registry.
    ctx = await load_tenant_by_id(tid)
    if ctx is None:
        return DeviceTenantResult(DeviceResolution.UNRESOLVED, tid=tid, reason="tenant_not_found")

    # 3. Authorization: the signed tid is a hint; membership is the truth.
    if not user_id or not await is_member(str(user_id), tid):
        return DeviceTenantResult(DeviceResolution.FORBIDDEN, tid=tid, reason="not_a_member")

    # 4. Good.
    return DeviceTenantResult(DeviceResolution.RESOLVED, context=ctx, tid=tid)
