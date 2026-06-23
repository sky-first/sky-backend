"""Daily LLM cost snapshot worker.

Runs once a day from Celery beat. For each active tenant, calls the
Langfuse-backed :class:`LlmCostMetricsProvider` for the previous day's
window and upserts a row into ``tenant_llm_daily_snapshots``. The
Console then reads from that table for the trend chart, falling back
to the live Langfuse API only for the last 24h slice the snapshot
hasn't captured yet.

Why daily and not real-time:

* Langfuse Cloud rate-limits at ~100 req/min/project; one full
  per-tenant scan covers all rows in a single burst, well below
  ceiling.
* The Console trend chart shows up to 30 days; a 24h snapshot
  granularity is fine for that surface.

Idempotency: the worker upserts on the unique (tenant_id,
snapshot_date) constraint, so re-running for the same day is safe.
This matches the pattern in ``src.workers.pricing_worker``.

Gate: ``LLM_METRICS_ENABLED`` controls whether the worker does any
real work. When the flag is off, the task returns ``{"skipped": True}``
immediately — same fail-soft contract as the service layer.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.config.settings import settings
from src.models.tenant import Tenant
from src.models.tenant_llm_daily_snapshot import TenantLlmDailySnapshot
from src.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


async def _list_active_tenants(session: AsyncSession) -> List[tuple[uuid.UUID, str]]:
    """Return ``(tenant_id, slug)`` pairs for every active tenant.

    Suspended / deleted tenants are skipped — their Langfuse traces
    still exist but they no longer drive cost decisions for Lucas's
    operational view, and we don't want stale rows growing forever.
    """
    rows = (
        await session.execute(
            select(Tenant.id, Tenant.slug).where(Tenant.is_active == True)  # noqa: E712
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _upsert_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    snapshot_date: date,
    metrics,
    langfuse_host: Optional[str],
) -> None:
    """Insert or update a single snapshot row.

    Uses Postgres ``INSERT … ON CONFLICT … DO UPDATE`` so the worker
    is safe to re-run for the same day. Falls back to a delete+insert
    on SQLite (which is what the test suite uses — its dialect doesn't
    support the Postgres-specific upsert).
    """
    if session.bind.dialect.name == "postgresql":
        stmt = pg_insert(TenantLlmDailySnapshot).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            snapshot_date=snapshot_date,
            total_requests=metrics.total_requests,
            total_input_tokens=metrics.total_input_tokens,
            total_output_tokens=metrics.total_output_tokens,
            total_cost_usd=metrics.total_cost_usd,
            total_cost_eur=metrics.total_cost_eur,
            cache_hit_rate_pct=metrics.cache_hit_rate_pct,
            avg_latency_ms=metrics.avg_latency_ms,
            by_model_json=metrics.by_model or {},
            langfuse_host=langfuse_host,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_tenant_llm_daily_snapshots_tenant_date",
            set_={
                "total_requests": stmt.excluded.total_requests,
                "total_input_tokens": stmt.excluded.total_input_tokens,
                "total_output_tokens": stmt.excluded.total_output_tokens,
                "total_cost_usd": stmt.excluded.total_cost_usd,
                "total_cost_eur": stmt.excluded.total_cost_eur,
                "cache_hit_rate_pct": stmt.excluded.cache_hit_rate_pct,
                "avg_latency_ms": stmt.excluded.avg_latency_ms,
                "by_model_json": stmt.excluded.by_model_json,
                "langfuse_host": stmt.excluded.langfuse_host,
            },
        )
        await session.execute(stmt)
        return

    # SQLite path (tests). Delete any existing row for the same key,
    # then insert. Not atomic across two statements but the test
    # suite runs single-threaded so it's safe.
    from sqlalchemy import delete

    await session.execute(
        delete(TenantLlmDailySnapshot)
        .where(TenantLlmDailySnapshot.tenant_id == tenant_id)
        .where(TenantLlmDailySnapshot.snapshot_date == snapshot_date)
    )
    session.add(
        TenantLlmDailySnapshot(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            snapshot_date=snapshot_date,
            total_requests=metrics.total_requests,
            total_input_tokens=metrics.total_input_tokens,
            total_output_tokens=metrics.total_output_tokens,
            total_cost_usd=metrics.total_cost_usd,
            total_cost_eur=metrics.total_cost_eur,
            cache_hit_rate_pct=metrics.cache_hit_rate_pct,
            avg_latency_ms=metrics.avg_latency_ms,
            by_model_json=metrics.by_model or {},
            langfuse_host=langfuse_host,
        )
    )


async def _snapshot_llm_metrics_async() -> Dict[str, Any]:
    """Take a snapshot for every active tenant, return a summary.

    The summary dict is what shows up in the Celery result; structured
    fields make it easy to alert on ``failures > 0`` from Prometheus
    or the Console's worker-health view.
    """
    if not settings.LLM_METRICS_ENABLED:
        logger.info("llm_metrics_snapshot_skipped", extra={"reason": "disabled"})
        return {"skipped": True, "reason": "LLM_METRICS_ENABLED=false"}

    # Yesterday's UTC date — running shortly after midnight UTC means
    # the previous day's data has stopped accumulating.
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    # Import inside the function so test paths that don't enable the
    # flag don't pay the cost of constructing the provider.
    from src.services.llm_cost_metrics import llm_cost_metrics_provider

    provider = llm_cost_metrics_provider()
    succeeded = 0
    failed = 0

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        tenants = await _list_active_tenants(session)
        for tenant_id, slug in tenants:
            try:
                metrics = provider.get_tenant_llm_metrics(tenant_id=slug, days=1)
                if not metrics.available:
                    # Treat "unavailable" as a soft failure — record
                    # zero so the trend chart doesn't show a gap, but
                    # increment the failed counter so an outage is
                    # visible in the Celery result.
                    failed += 1
                await _upsert_snapshot(
                    session,
                    tenant_id=tenant_id,
                    snapshot_date=yesterday,
                    metrics=metrics,
                    langfuse_host=settings.LANGFUSE_HOST,
                )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(
                    "llm_metrics_snapshot_tenant_failed",
                    extra={"tenant_slug": slug, "error": str(exc)},
                )
        await session.commit()

    logger.info(
        "llm_metrics_snapshot_done",
        extra={
            "snapshot_date": yesterday.isoformat(),
            "tenants": len(tenants),
            "succeeded": succeeded,
            "failed": failed,
        },
    )
    return {
        "snapshot_date": yesterday.isoformat(),
        "tenants": len(tenants),
        "succeeded": succeeded,
        "failed": failed,
    }


@celery_app.task(name="src.workers.llm_metrics_worker.snapshot_llm_metrics")
def snapshot_llm_metrics() -> dict:
    """Celery entry point — sync wrapper around the async helper."""
    return asyncio.run(_snapshot_llm_metrics_async())


__all__ = ["snapshot_llm_metrics"]
