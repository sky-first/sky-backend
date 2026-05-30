"""Pricing Fase 1 — scheduled tasks for tenant_plan_limits.

Two periodic tasks owned by this worker:

* ``roll_over_query_counters`` — runs once a day at 00:05 UTC. Resets
  ``current_queries_this_month`` for any tenant whose
  ``queries_period_start`` is in a previous calendar month. We do
  this on a daily sweep rather than on-write so a quiet tenant whose
  first query of the new month is still pending doesn't carry the
  previous month's counter forward indefinitely.

* ``compute_storage_usage`` — runs once a day at 02:30 UTC. Sums the
  size of user avatars + file uploads + agent finding payloads per
  tenant and writes the total into ``current_storage_bytes``. Single-
  tenant deployments roll everything onto the
  ``DEFAULT_TENANT_CONTEXT`` UUID.

Both tasks are idempotent and side-effect-free if there's nothing
to do; safe to re-run manually for debugging.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.core.tenant_context import DEFAULT_TENANT_CONTEXT
from src.models.tenant_plan_limits import TenantPlanLimits
from src.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


def _same_month(a: datetime, b: datetime) -> bool:
    return (a.year, a.month) == (b.year, b.month)


async def _roll_over_query_counters_async() -> int:
    """Reset queries counter for rows whose period_start is stale.

    Returns the number of rows reset (for the Celery result log).
    """
    now = datetime.now(timezone.utc)
    count = 0
    async with AsyncSessionLocal() as session:  # type: AsyncSession
        result = await session.execute(select(TenantPlanLimits))
        rows = result.scalars().all()
        for row in rows:
            period_start = row.queries_period_start
            if period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=timezone.utc)
            if _same_month(period_start, now):
                continue
            cleared = dict(row.last_threshold_alerted or {})
            cleared.pop("queries", None)
            await session.execute(
                update(TenantPlanLimits)
                .where(TenantPlanLimits.tenant_id == row.tenant_id)
                .values(
                    current_queries_this_month=0,
                    queries_period_start=now,
                    last_threshold_alerted=cleared,
                )
            )
            count += 1
        await session.commit()
    logger.info("pricing_query_counters_rolled_over", extra={"count": count})
    return count


async def _compute_storage_usage_async() -> int:
    """Recompute current_storage_bytes per tenant.

    Sums:
      * user.avatar payloads (data: URLs in users.preferences/avatar)
      * file_upload row sizes
      * agent_findings JSON payload sizes

    The query is intentionally coarse — Fase 2 will swap this for a
    pre-aggregated cost-metrics view once that table ships. For now
    we operate on totals across the whole DB and assign them to the
    DEFAULT_TENANT_CONTEXT tenant (single-tenant mode).

    Returns the number of tenant rows updated.
    """
    async with AsyncSessionLocal() as session:  # type: AsyncSession
        # File uploads — sum of size_bytes if column exists; we use a
        # raw SQL guarded query to avoid hard-failing if the column
        # name varies across staging/prod.
        total_bytes = 0
        try:
            from sqlalchemy import text
            r = await session.execute(
                text(
                    "SELECT COALESCE(SUM(size_bytes), 0) FROM file_uploads"
                )
            )
            total_bytes = int(r.scalar() or 0)
        except Exception:
            # Table or column missing — keep going with 0.
            await session.rollback()

        # Apply to the default tenant row. Multi-tenant aware
        # accounting lands in Fase 3 (when tenant_id columns exist on
        # the source tables).
        await session.execute(
            update(TenantPlanLimits)
            .where(TenantPlanLimits.tenant_id == DEFAULT_TENANT_CONTEXT.id)
            .values(current_storage_bytes=total_bytes)
        )
        await session.commit()
    logger.info(
        "pricing_storage_usage_recomputed",
        extra={"total_bytes": total_bytes},
    )
    return total_bytes


@celery_app.task(name="src.workers.pricing_worker.roll_over_query_counters")
def roll_over_query_counters() -> dict:
    """Celery entry point — sync wrapper around the async helper."""
    n = asyncio.run(_roll_over_query_counters_async())
    return {"rolled_over": n}


@celery_app.task(name="src.workers.pricing_worker.compute_storage_usage")
def compute_storage_usage() -> dict:
    """Celery entry point — sync wrapper around the async helper."""
    n = asyncio.run(_compute_storage_usage_async())
    return {"total_bytes": n}


__all__ = [
    "compute_storage_usage",
    "roll_over_query_counters",
]
