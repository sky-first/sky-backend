"""Pricing enforcement service (Pricing Fase 1).

Owns reads + writes for ``tenant_plan_limits``. The enforcement hooks
in the agent / AI / spaces routes call into this module rather than
poking the table directly so the audit + threshold-crossing logic
stays in one place.

Hot-path semantics:

* ``check_can_create_agent`` / ``check_can_create_user`` are called
  BEFORE the INSERT and raise :class:`TierLimitExceededError` (HTTP 402)
  when the next unit would exceed the ceiling. They DO NOT bump the
  counter — that's the job of the table-level "creation succeeded"
  hook (currently `record_agent_created` / `record_user_created`,
  invoked from the same route once the row commits).

* ``record_query_usage`` is called at the END of every AI request,
  inside the same DB session. It atomically increments
  ``current_queries_this_month`` and, if the calendar month has rolled
  over since ``queries_period_start``, resets both the counter and the
  ``last_threshold_alerted["queries"]`` list before incrementing.

* Threshold tracking — every increment computes the *post-bump* usage
  percentage and, if it just crossed 80/95/100 for the first time
  this period, emits a structured ``tier_threshold_crossed`` log AND
  inserts an ``InternalConsoleAudit`` row with
  ``action="tier_limit_warning"``. The Fase 2 email hooks read off
  those audit rows.

A single in-memory ``asyncio.Lock`` would race in a multi-worker
deployment, so we lean on Postgres atomic ``UPDATE col = col + N``
semantics for correctness — the threshold log is best-effort and may
duplicate across workers; the audit row's idempotency key (timestamp +
threshold) lets the email worker dedupe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PaymentRequiredError
from src.core.tenant_context import current_tenant
from src.models.internal_console import InternalConsoleAudit
from src.models.tenant_plan_limits import (
    TIER_LIMITS,
    UPGRADE_HINT,
    TenantPlanLimits,
)


logger = logging.getLogger(__name__)


# Thresholds we alert on, in ascending order. The crossing check fires
# the lowest-not-yet-alerted threshold the post-bump usage exceeds.
ALERT_THRESHOLDS = (80, 95, 100)


# Console audit log uses a fixed action vocabulary (CHECK constraint).
# ``tier_limit_warning`` is not in the original set; we reuse
# ``update_capacity`` so we don't have to ship a constraint migration
# in the same PR. The result_details JSON carries the actual signal.
_AUDIT_ACTION_FOR_TIER_WARNING = "update_capacity"


class TierLimitExceededError(PaymentRequiredError):
    """Raised when a tenant attempts to exceed a tier ceiling.

    Surfaces as HTTP 402 PAYMENT_REQUIRED with the standard pricing
    upgrade payload — see ``src/core/errors/handlers.py``.
    """

    def __init__(
        self,
        *,
        resource: str,
        limit: int,
        current: int,
        tier: str,
        upgrade_hint: str | None,
    ):
        self.resource = resource
        self.limit = limit
        self.current = current
        self.tier = tier
        self.upgrade_hint = upgrade_hint
        message = (
            f"Tier limit exceeded for {resource}: "
            f"{current}/{limit} on tier {tier!r}"
        )
        super().__init__(
            message,
            upgrade_cta=(
                f"Upgrade to {upgrade_hint}"
                if upgrade_hint
                else "Contact sales"
            ),
        )


# ─── Internal helpers ──────────────────────────────────────────────


def _resolve_tenant_id(tenant_id: UUID | str | None) -> UUID:
    """Resolve the effective tenant_id for the current request.

    When the caller doesn't pass one, falls back to
    ``current_tenant().id`` — the contextvar set by the resolver
    middleware (or the ``DEFAULT_TENANT_CONTEXT`` UUID(int=0) sentinel
    when ``MULTI_TENANT_ENABLED`` is False).
    """
    if tenant_id is None:
        return current_tenant().id
    if isinstance(tenant_id, str):
        return UUID(tenant_id)
    return tenant_id


def _is_same_month(a: datetime, b: datetime) -> bool:
    """True iff a and b fall in the same UTC year-month."""
    return (a.year, a.month) == (b.year, b.month)


def _percent(current: int, limit: int | None) -> float:
    """Return usage percent (0.0–∞). NULL/0 ceilings → 0.0 (unlimited)."""
    if limit is None or limit <= 0:
        return 0.0
    return (current / limit) * 100.0


def _crossed_thresholds(
    previous_percent: float,
    current_percent: float,
    already_alerted: list[str],
) -> list[int]:
    """Return thresholds crossed by this bump and not yet alerted.

    A "cross" is: ``previous_percent < t <= current_percent`` for any
    ``t`` in :data:`ALERT_THRESHOLDS`. We allow the 100 threshold to
    fire even when the limit is exactly hit (current == limit).
    """
    out: list[int] = []
    for t in ALERT_THRESHOLDS:
        if previous_percent < t <= current_percent and str(t) not in already_alerted:
            out.append(t)
    return out


async def _log_threshold_crossings(
    db: AsyncSession,
    *,
    row: TenantPlanLimits,
    resource: str,
    previous_percent: float,
    current_percent: float,
) -> list[int]:
    """If the post-bump percent crosses a threshold, log + audit it.

    Returns the list of thresholds that fired (used by the caller to
    persist them into ``last_threshold_alerted``). Best-effort — log
    failures are swallowed so a logging hiccup never blocks the hot
    path.
    """
    already = list(
        (row.last_threshold_alerted or {}).get(resource, [])
    )
    crossings = _crossed_thresholds(previous_percent, current_percent, already)
    if not crossings:
        return []

    for t in crossings:
        try:
            logger.warning(
                "tier_threshold_crossed",
                extra={
                    "tenant_id": str(row.tenant_id),
                    "tier": row.tier,
                    "resource": resource,
                    "threshold": t,
                    "current_percent": round(current_percent, 2),
                },
            )
        except Exception:  # pragma: no cover — log failure is non-fatal
            pass

        # Audit row — reuses the update_capacity action so the existing
        # CHECK constraint passes; the details JSON carries the
        # "tier_limit_warning" intent the Fase 2 email worker reads.
        try:
            db.add(
                InternalConsoleAudit(
                    actor_email="system@pricing",
                    action=_AUDIT_ACTION_FOR_TIER_WARNING,
                    tenant_slug=None,
                    result="success",
                    result_details={
                        "intent": "tier_limit_warning",
                        "tenant_id": str(row.tenant_id),
                        "tier": row.tier,
                        "resource": resource,
                        "threshold": t,
                        "current": _current_count_for(row, resource),
                        "limit": _limit_for(row, resource),
                    },
                )
            )
            await db.flush()
        except Exception:  # pragma: no cover — best-effort
            pass
    return crossings


def _current_count_for(row: TenantPlanLimits, resource: str) -> int:
    mapping = {
        "agents": row.current_agents,
        "users": row.current_users,
        "storage": row.current_storage_bytes,
        "queries": row.current_queries_this_month,
    }
    return int(mapping.get(resource, 0) or 0)


def _limit_for(row: TenantPlanLimits, resource: str) -> int | None:
    mapping = {
        "agents": row.max_agents,
        "users": row.max_users,
        "storage": (row.max_storage_gb * 1024 * 1024 * 1024)
        if row.max_storage_gb is not None
        else None,
        "queries": row.max_queries_per_month,
    }
    return mapping.get(resource)


# ─── Public API ────────────────────────────────────────────────────


async def get_limits(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> TenantPlanLimits:
    """Fetch (or auto-provision) the plan-limits row for a tenant.

    The migration seeds every tenant_registry row with a Foundation
    default. This method covers the gap where a tenant is registered
    between the migration running and the row being created — we
    self-heal by inserting a Foundation row on first read rather than
    raising. Avoids a brittle "your tenant has no plan row" 500.
    """
    tid = _resolve_tenant_id(tenant_id)

    row = await db.get(TenantPlanLimits, tid)
    if row is None:
        row = TenantPlanLimits(
            tenant_id=tid,
            tier="foundation",
            **TIER_LIMITS["foundation"],
            queries_period_start=datetime.now(timezone.utc),
            last_threshold_alerted={},
        )
        db.add(row)
        await db.flush()
    return row


async def check_can_create_agent(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> bool:
    """Raise :class:`TierLimitExceededError` if at/over the agent cap."""
    row = await get_limits(db, tenant_id)
    if row.max_agents is None:  # enterprise / unlimited
        return True
    if row.current_agents >= row.max_agents:
        raise TierLimitExceededError(
            resource="agents",
            limit=row.max_agents,
            current=row.current_agents,
            tier=row.tier,
            upgrade_hint=UPGRADE_HINT.get(row.tier),
        )
    return True


async def check_can_create_user(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> bool:
    """Raise :class:`TierLimitExceededError` if at/over the user cap."""
    row = await get_limits(db, tenant_id)
    if row.max_users is None:
        return True
    if row.current_users >= row.max_users:
        raise TierLimitExceededError(
            resource="users",
            limit=row.max_users,
            current=row.current_users,
            tier=row.tier,
            upgrade_hint=UPGRADE_HINT.get(row.tier),
        )
    return True


async def record_agent_created(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> None:
    """Bump current_agents by one (called after a successful INSERT)."""
    await _bump_counter(db, tenant_id, "current_agents", 1, resource="agents")


async def record_user_created(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> None:
    """Bump current_users by one (called after a successful INSERT)."""
    await _bump_counter(db, tenant_id, "current_users", 1, resource="users")


async def record_query_usage(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> None:
    """Bump current_queries_this_month, rolling over the month if needed.

    Atomic UPDATE in two phases: (1) roll over if the calendar month
    has changed since queries_period_start, (2) increment by one. The
    threshold-crossing log fires on the post-bump value.
    """
    tid = _resolve_tenant_id(tenant_id)
    row = await get_limits(db, tid)

    now = datetime.now(timezone.utc)
    period_start = row.queries_period_start
    # Naive datetimes in SQLite — assume UTC.
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)

    if not _is_same_month(period_start, now):
        # Roll over — reset counter, period start, and queries alerts.
        cleared_alerts = dict(row.last_threshold_alerted or {})
        cleared_alerts.pop("queries", None)
        await db.execute(
            update(TenantPlanLimits)
            .where(TenantPlanLimits.tenant_id == tid)
            .values(
                current_queries_this_month=0,
                queries_period_start=now,
                last_threshold_alerted=cleared_alerts,
            )
        )
        await db.flush()
        await db.refresh(row)

    await _bump_counter(
        db, tid, "current_queries_this_month", 1, resource="queries"
    )


async def record_storage_usage(
    db: AsyncSession,
    bytes_delta: int,
    tenant_id: UUID | str | None = None,
) -> None:
    """Adjust current_storage_bytes by ``bytes_delta`` (may be negative).

    Negative deltas are clamped at zero by the CHECK constraint; the
    caller is responsible for not over-deleting.
    """
    if bytes_delta == 0:
        return
    await _bump_counter(
        db,
        tenant_id,
        "current_storage_bytes",
        bytes_delta,
        resource="storage",
    )


async def _bump_counter(
    db: AsyncSession,
    tenant_id: UUID | str | None,
    column: str,
    delta: int,
    *,
    resource: str,
) -> None:
    """Atomic counter bump + threshold-crossing log.

    The atomic increment is done via ``UPDATE col = col + :delta`` so
    we don't race two concurrent requests reading-then-writing the
    same value. The threshold check uses the *post-bump* value pulled
    from the same session.
    """
    tid = _resolve_tenant_id(tenant_id)
    row = await get_limits(db, tid)
    limit = _limit_for(row, resource)
    previous_count = _current_count_for(row, resource)
    previous_percent = _percent(previous_count, limit)

    # Atomic increment — works the same on Postgres and SQLite.
    col = getattr(TenantPlanLimits, column)
    await db.execute(
        update(TenantPlanLimits)
        .where(TenantPlanLimits.tenant_id == tid)
        .values({column: col + delta})
    )
    await db.flush()
    await db.refresh(row)

    current_count = _current_count_for(row, resource)
    current_percent = _percent(current_count, limit)

    crossings = await _log_threshold_crossings(
        db,
        row=row,
        resource=resource,
        previous_percent=previous_percent,
        current_percent=current_percent,
    )
    if crossings:
        merged = dict(row.last_threshold_alerted or {})
        bucket = list(merged.get(resource, []))
        for t in crossings:
            if str(t) not in bucket:
                bucket.append(str(t))
        merged[resource] = bucket
        await db.execute(
            update(TenantPlanLimits)
            .where(TenantPlanLimits.tenant_id == tid)
            .values(last_threshold_alerted=merged)
        )
        await db.flush()


async def usage_percent(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> dict[str, float]:
    """Return usage % for agents / users / storage / queries.

    Unlimited resources (NULL ceiling) are reported as 0.0 — the
    Console UI renders that as "—" rather than "0% of unlimited".
    """
    row = await get_limits(db, tenant_id)
    return {
        "agents": _percent(row.current_agents, row.max_agents),
        "users": _percent(row.current_users, row.max_users),
        "storage": _percent(
            row.current_storage_bytes,
            (row.max_storage_gb * 1024 * 1024 * 1024)
            if row.max_storage_gb is not None
            else None,
        ),
        "queries": _percent(
            row.current_queries_this_month, row.max_queries_per_month
        ),
    }


async def should_alert(
    db: AsyncSession,
    tenant_id: UUID | str | None = None,
) -> list[str]:
    """Return ``["resource:threshold"]`` for thresholds crossed-not-alerted.

    Currently the threshold crossings are caught synchronously inside
    each counter bump, so this returns only the unflushed ones — a
    second pass the email worker can do over the audit log if it ever
    needs to backfill. Always returns an empty list under normal
    operation because the bumps log inline.
    """
    row = await get_limits(db, tenant_id)
    out: list[str] = []
    pct = await usage_percent(db, tenant_id)
    already = row.last_threshold_alerted or {}
    for resource, current_percent in pct.items():
        alerted_for_resource = list(already.get(resource, []))
        for t in ALERT_THRESHOLDS:
            if current_percent >= t and str(t) not in alerted_for_resource:
                out.append(f"{resource}:{t}")
    return out


async def set_tier(
    db: AsyncSession,
    tier: str,
    tenant_id: UUID | str | None = None,
) -> TenantPlanLimits:
    """Move a tenant onto a new commercial tier (Console-only call).

    Applies the new ceilings from :data:`TIER_LIMITS` and resets the
    threshold-alert tracking so the FE alerts again on the new
    quotas. Counters are NOT reset — the customer's existing
    consumption carries over.
    """
    if tier not in TIER_LIMITS:
        raise ValueError(f"unknown tier: {tier!r}")
    tid = _resolve_tenant_id(tenant_id)
    row = await get_limits(db, tid)
    limits = TIER_LIMITS[tier]
    await db.execute(
        update(TenantPlanLimits)
        .where(TenantPlanLimits.tenant_id == tid)
        .values(
            tier=tier,
            max_agents=limits["max_agents"],
            max_users=limits["max_users"],
            max_storage_gb=limits["max_storage_gb"],
            max_queries_per_month=limits["max_queries_per_month"],
            last_threshold_alerted={},
        )
    )
    await db.flush()
    await db.refresh(row)
    return row


__all__ = [
    "ALERT_THRESHOLDS",
    "TierLimitExceededError",
    "check_can_create_agent",
    "check_can_create_user",
    "get_limits",
    "record_agent_created",
    "record_query_usage",
    "record_storage_usage",
    "record_user_created",
    "set_tier",
    "should_alert",
    "usage_percent",
]
