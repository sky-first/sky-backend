"""Tenant guard utilities (Projeto A — PR #14).

Once a tenant has been cut over (``MULTI_TENANT_ENABLED=true`` AND the
tenant has a registry row), any DB session opened in the request path
should be tenant-scoped. The graceful fallback to the default context
during Phase 1-4 makes the transition safe, but once it is complete we
want loud noise the moment something slips through unscoped — that is
the smell of a code path that bypasses the resolver.

This module exposes a single helper, :func:`assert_tenant_scoped`,
that handlers can call when they reach business logic that MUST run
under a real tenant (e.g. the GBT-only paid features). Calling it on
the default context emits a structured warning log and — if
``STRICT_TENANT_REQUIRED`` is set — raises a 400.

Default behaviour is "log only" so flipping the flag for a single
tenant does not break the platform for every other one that is still
on the legacy path. PR #15's cleanup step removes the log-only escape
hatch once every tenant has been migrated.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from src.config.settings import settings
from src.core.tenant_context import TenantContext, current_tenant

logger = logging.getLogger(__name__)


def assert_tenant_scoped(
    operation: str,
    *,
    ctx: Optional[TenantContext] = None,
    hard_fail: Optional[bool] = None,
) -> TenantContext:
    """Assert the current request is operating against a real tenant.

    * ``operation`` — short label that appears in the log line so the
      offending call site is identifiable from telemetry.
    * ``ctx`` — override the looked-up context (useful in tests).
    * ``hard_fail`` — if True, raise ``HTTPException(400)`` instead of
      just logging. Defaults to ``settings.STRICT_TENANT_REQUIRED``.

    Returns the validated context so callers can chain: ``tenant =
    assert_tenant_scoped("agent.run")``.

    No-op when ``MULTI_TENANT_ENABLED`` is False — that is the legal
    state during Phase 1-4 and the helper would otherwise scream on
    every request.
    """
    resolved = ctx if ctx is not None else current_tenant()
    if not settings.MULTI_TENANT_ENABLED:
        return resolved
    if not resolved.is_default:
        return resolved

    payload = {"operation": operation, "tenant_slug": resolved.slug}
    logger.warning("tenant_scope_violation", extra=payload)

    strict = settings.STRICT_TENANT_REQUIRED if hard_fail is None else hard_fail
    if strict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "tenant_scope_required",
                "operation": operation,
                "hint": "Send X-Tenant-Slug or call via a workspace-* hostname.",
            },
        )
    return resolved
