"""Celery → tenant_context propagation (Projeto A — PR #8).

The idea: when a request handler enqueues a Celery task, the active
:class:`TenantContext` should travel with the message so the worker
that eventually runs the task can rebuild it locally. We achieve that
with three Celery signals:

* ``before_task_publish`` — runs in the producing process (the
  FastAPI app). Reads ``current_tenant()`` and writes its slug into
  the task headers so it survives the broker round-trip.
* ``task_prerun`` — runs in the worker process. Pulls the slug out of
  the task headers, looks up the tenant from the registry (via the
  cache used by the resolver), and sets the contextvar.
* ``task_postrun`` — resets the contextvar to avoid leaking the
  tenant into the next task on the same prefork.

While ``MULTI_TENANT_ENABLED`` is False the publish step still copies
``"default"`` into the headers and the prerun step keeps the contextvar
on the default tenant — i.e. no behaviour change.

Workers that read DB state through ``get_db_session_for_context`` (or
through ``tenant_connection_manager.session_for(current_tenant())``)
automatically operate against the right tenant DB once the flag is on.
Workers still calling ``AsyncSessionLocal`` directly remain on the
global pool — Phase 4 migrates those callers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from celery.signals import (
    before_task_publish,
    task_postrun,
    task_prerun,
)

from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)

logger = logging.getLogger(__name__)


# Header key for the slug. Celery encodes headers into the AMQP message
# properties — short, lowercase, no underscores in the wire format.
_TENANT_HEADER = "x-tenant-slug"

# Stash for the reset token, keyed on Celery's task_id so before/after
# pairs match cleanly even when the same prefork serves many tasks.
_RESET_TOKENS: Dict[str, Any] = {}


# ─── Publish side (in the FastAPI app process) ─────────────────────


@before_task_publish.connect
def _attach_tenant_slug_to_headers(
    sender: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
    **kwargs: Any,
) -> None:
    """Copy the current tenant slug into the outgoing message headers.

    Celery passes the existing headers dict by reference; mutating it
    in place is what the docs recommend. If the contextvar has not
    been set we still write ``"default"`` so the receiving side has a
    predictable shape — no special-case branching in ``task_prerun``.
    """
    if headers is None:
        # Celery should always pass a dict, but defensively short-circuit.
        return
    ctx = current_tenant()
    headers[_TENANT_HEADER] = ctx.slug


# ─── Run side (in each worker process) ─────────────────────────────


@task_prerun.connect
def _set_tenant_from_headers(
    task_id: Optional[str] = None,
    task=None,
    **kwargs: Any,
) -> None:
    """Restore the tenant context for the worker before the task runs.

    Looks up the slug in the task's request headers. When the slug is
    missing or is the default we set ``DEFAULT_TENANT_CONTEXT``; when
    it names a real tenant we hit the registry cache (and, on miss,
    the DB) via the resolver's loader.

    Worker code that wants the full ``TenantContext`` (rate limits,
    feature flags) calls ``current_tenant()`` — same API the request
    handlers use.
    """
    slug = _slug_from_task(task)

    if not slug or slug == DEFAULT_TENANT_CONTEXT.slug:
        token = set_current_tenant(DEFAULT_TENANT_CONTEXT)
        if task_id:
            _RESET_TOKENS[task_id] = token
        return

    ctx = _resolve_worker_side(slug)
    token = set_current_tenant(ctx)
    if task_id:
        _RESET_TOKENS[task_id] = token


@task_postrun.connect
def _reset_tenant_after_task(
    task_id: Optional[str] = None,
    task=None,
    **kwargs: Any,
) -> None:
    """Reset the contextvar so the next task on this prefork starts clean."""
    if task_id is None:
        return
    token = _RESET_TOKENS.pop(task_id, None)
    if token is not None:
        try:
            reset_current_tenant(token)
        except (ValueError, LookupError):
            # The contextvar API raises if the token's parent context
            # already exited. Either way we want the next task to
            # start from the default.
            set_current_tenant(DEFAULT_TENANT_CONTEXT)


# ─── Helpers ──────────────────────────────────────────────────────


def _slug_from_task(task) -> Optional[str]:
    """Extract the tenant slug stored by ``_attach_tenant_slug_to_headers``.

    The structure Celery hands the worker is:

      task.request.headers  →  dict with our ``x-tenant-slug`` entry

    Some workers (especially in tests) don't have a ``request``
    attribute; treat that as "no slug → default".
    """
    if task is None:
        return None
    request = getattr(task, "request", None)
    if request is None:
        return None
    headers = getattr(request, "headers", None) or {}
    slug = headers.get(_TENANT_HEADER)
    return slug if isinstance(slug, str) else None


def _resolve_worker_side(slug: str) -> TenantContext:
    """Look up a tenant on the worker side.

    Avoids the FastAPI-only resolver path. We call the same loader the
    middleware uses, which respects the shared cache, so the first task
    for a tenant pays the DB lookup and subsequent ones are free.

    On any failure (registry table missing, network issue, …) returns
    the default context — workers should keep making progress even if
    the tenant cannot be resolved; the per-task code that needs strict
    tenant-scoping must check ``ctx.is_default`` itself.
    """
    import asyncio

    from src.api.middleware.tenant_resolver import (
        _cache_get,
        _cache_put,
        _load_tenant_from_db,
    )

    cached = _cache_get(slug)
    if cached is not None:
        return cached

    try:
        ctx = asyncio.run(_load_tenant_from_db(slug))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "worker_tenant_resolve_failed",
            extra={"slug": slug, "error": str(exc)},
        )
        return DEFAULT_TENANT_CONTEXT

    if ctx is None:
        return DEFAULT_TENANT_CONTEXT

    _cache_put(ctx)
    return ctx


__all__ = [
    "_TENANT_HEADER",
    "_attach_tenant_slug_to_headers",
    "_set_tenant_from_headers",
    "_reset_tenant_after_task",
]
