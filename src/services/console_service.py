"""Service layer for the Internal Console (Projeto B).

Routes call this layer; the layer calls repositories / the ORM directly
because the Console has a small surface and a separate repository tier
would be overkill for now.

The shape is "operate on the platform DB only" — Console actions never
need a tenant-scoped session because every concern (registry rows,
audit log, provisioning jobs) lives in the platform DB next to
``tenant_registry``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.tenant_resolver import clear_tenant_cache
from src.models.internal_console import (
    AuditAction,
    AuditResult,
    InternalConsoleAudit,
    ProvisioningJob,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.models.tenant import Tenant
from src.models.tenant_plan_limits import TenantPlanLimits
from src.schemas.internal_console import (
    AuditEntryRead,
    ConsoleTenantDetail,
    ConsoleTenantList,
    ConsoleTenantSummary,
    CreateTenantRequest,
    DashboardSummary,
    DestroyTenantRequest,
    ProvisioningJobRead,
    SuspendTenantRequest,
    UpdateTenantRequest,
)

logger = logging.getLogger(__name__)


_DESTROY_CONFIRMATION_PHRASE = "I understand this is irreversible"


# ── Tenants ────────────────────────────────────────────────────────


async def list_tenants(
    db: AsyncSession,
    *,
    tier: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> ConsoleTenantList:
    """List tenants with optional filters.

    ``capacity_pct_*`` and ``health_score`` are computed from the live
    ``tenant_plan_limits`` counters (current_agents, current_users,
    current_storage_bytes, current_queries_this_month) rather than the
    stale ``capacity_used`` JSONB on tenant_registry, which has never
    been backed by a sync task.
    """
    stmt = select(Tenant)
    if tier is not None:
        stmt = stmt.where(Tenant.tier == tier)
    if is_active is not None:
        stmt = stmt.where(Tenant.is_active == is_active)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Tenant.slug).like(like)
            | func.lower(Tenant.display_name).like(like)
        )

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    # Batch-fetch plan limits for all tenants in one query — avoids N+1.
    tenant_ids = [row.id for row in rows]
    plan_by_id: Dict[Any, TenantPlanLimits] = {}
    if tenant_ids:
        plan_rows = (
            await db.execute(
                select(TenantPlanLimits).where(
                    TenantPlanLimits.tenant_id.in_(tenant_ids)
                )
            )
        ).scalars().all()
        for p in plan_rows:
            plan_by_id[p.tenant_id] = p

    # Latest pending/running provisioning job per tenant_slug, in one
    # query. PostgreSQL ``DISTINCT ON`` returns the first row per group
    # given the ORDER BY, so we get the freshest job per tenant without
    # a per-row N+1 fan-out. Idle tenants simply have no entry in the map.
    slugs = [row.slug for row in rows]
    active_jobs_by_slug: Dict[str, ProvisioningJob] = {}
    if slugs:
        active_stmt = (
            select(ProvisioningJob)
            .where(
                ProvisioningJob.tenant_slug.in_(slugs),
                ProvisioningJob.status.in_(
                    [
                        ProvisioningJobStatus.PENDING.value,
                        ProvisioningJobStatus.RUNNING.value,
                    ]
                ),
            )
            .order_by(
                ProvisioningJob.tenant_slug,
                ProvisioningJob.started_at.desc(),
            )
            .distinct(ProvisioningJob.tenant_slug)
        )
        for job in (await db.execute(active_stmt)).scalars().all():
            active_jobs_by_slug[job.tenant_slug] = job

    items = [
        ConsoleTenantSummary(
            slug=row.slug,
            display_name=row.display_name,
            tier=row.tier,
            is_active=row.is_active,
            suspended_at=row.suspended_at,
            custom_domain=row.custom_domain,
            created_at=row.created_at,
            capacity_pct_agents=_pct_from_plan(plan_by_id.get(row.id), "agents"),
            capacity_pct_sources=_pct_from_plan(plan_by_id.get(row.id), "users"),
            capacity_pct_indexed_gb=_pct_from_plan(plan_by_id.get(row.id), "storage"),
            health_score=_health_score_from_plan(plan_by_id.get(row.id)),
            is_unlimited=_is_unlimited(plan_by_id.get(row.id)),
            active_job=(
                ProvisioningJobRead.model_validate(active_jobs_by_slug[row.slug])
                if row.slug in active_jobs_by_slug
                else None
            ),
        )
        for row in rows
    ]
    items.sort(key=lambda t: t.health_score, reverse=True)
    return ConsoleTenantList(items=items, total=total)


async def get_tenant_detail(
    db: AsyncSession, slug: str
) -> Optional[ConsoleTenantDetail]:
    """Return registry row + most-recent audit + most-recent jobs."""
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        return None

    recent_audit_rows = (
        await db.execute(
            select(InternalConsoleAudit)
            .where(InternalConsoleAudit.tenant_slug == slug)
            .order_by(InternalConsoleAudit.timestamp.desc())
            .limit(50)
        )
    ).scalars().all()

    recent_jobs_rows = (
        await db.execute(
            select(ProvisioningJob)
            .where(ProvisioningJob.tenant_slug == slug)
            .order_by(ProvisioningJob.started_at.desc())
            .limit(10)
        )
    ).scalars().all()

    base = ConsoleTenantDetail.model_validate(row).model_dump()
    base["recent_audit"] = [AuditEntryRead.model_validate(r) for r in recent_audit_rows]
    base["recent_jobs"] = [ProvisioningJobRead.model_validate(r) for r in recent_jobs_rows]
    return ConsoleTenantDetail(**base)


async def create_tenant(
    db: AsyncSession,
    payload: CreateTenantRequest,
    *,
    actor_email: str,
) -> tuple[ConsoleTenantDetail, ProvisioningJob]:
    """Insert a registry row + spawn a CREATE provisioning job.

    The actual provisioning (alembic upgrade on the tenant DB, admin
    user seed) happens out-of-band via the bootstrap_tenant.py script —
    in this MVP the job tracks intent; v1.1 wires it to a Celery task
    that actually runs the script.

    Raises ``ValueError("slug_taken")`` on uniqueness violations so the
    route can map it to a clean 409.
    """
    # Strip the admin_email out of the registry payload; it travels with
    # the provisioning job instead so the bootstrap step can pick it up.
    body = payload.model_dump(exclude={"admin_email"})

    tenant = Tenant(
        slug=body["slug"],
        display_name=body["display_name"],
        tier=body["tier"].value if hasattr(body["tier"], "value") else body["tier"],
        db_host=body["db_host"],
        db_port=body["db_port"],
        db_name=body["db_name"],
        db_credentials_secret_arn=body["db_credentials_secret_arn"],
        redis_host=body["redis_host"],
        redis_credentials_secret_arn=body["redis_credentials_secret_arn"],
        bedrock_inference_profile_arn=body.get("bedrock_inference_profile_arn"),
        rate_limit_rpm=body["rate_limit_rpm"],
        rate_limit_tpm=body["rate_limit_tpm"],
        sso_provider=body["sso_provider"],
        sso_config=body["sso_config"],
        sso_domain_restriction=body.get("sso_domain_restriction"),
        custom_domain=body.get("custom_domain"),
        logo_url=body.get("logo_url"),
        feature_flags=body["feature_flags"],
        capacity_limits=body["capacity_limits"] if isinstance(body["capacity_limits"], dict)
        else body["capacity_limits"].model_dump(),
        auth_methods=body["auth_methods"] if isinstance(body["auth_methods"], dict)
        else body["auth_methods"].model_dump(),
    )
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        msg = str(exc).lower()
        if (
            "uq_tenant_registry_slug" in msg
            or "duplicate" in msg
            or "unique constraint failed: tenant_registry.slug" in msg
        ):
            raise ValueError("slug_taken") from exc
        raise

    job_payload: Dict[str, Any] = {
        "tenant_slug": tenant.slug,
        "tier": tenant.tier,
    }
    if payload.admin_email:
        job_payload["admin_email"] = payload.admin_email

    job = ProvisioningJob(
        tenant_slug=tenant.slug,
        actor_email=actor_email,
        job_type=ProvisioningJobType.CREATE.value,
        status=ProvisioningJobStatus.PENDING.value,
        request_payload=job_payload,
    )
    db.add(job)
    await db.flush()

    # Fire-and-forget the GitHub Actions dispatch. Lazy-imported so this
    # service module stays importable when Celery isn't configured
    # (tests, local Sky-team scripts). Failures here must NOT bubble:
    # the job row already exists, the UI can retry, and Celery will
    # surface its own error path via the job ``status`` column.
    try:
        from src.workers.celery_app import celery_app

        celery_app.send_task(
            "src.workers.provisioning_worker.provision_tenant_via_gh_actions",
            args=[str(job.id)],
        )
    except Exception as exc:  # pragma: no cover — broker outage is non-fatal
        logger.warning(
            "create_tenant: failed to enqueue provision_tenant_via_gh_actions "
            "for job %s: %s",
            job.id,
            exc,
        )

    detail = await get_tenant_detail(db, tenant.slug)
    assert detail is not None
    return detail, job


async def update_tenant(
    db: AsyncSession,
    slug: str,
    payload: UpdateTenantRequest,
) -> Optional[ConsoleTenantDetail]:
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        return None
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "tier" and hasattr(value, "value"):
            value = value.value
        if key == "capacity_limits" and not isinstance(value, dict) and value is not None:
            value = value.model_dump()
        if key == "auth_methods" and not isinstance(value, dict) and value is not None:
            value = value.model_dump()
        setattr(row, key, value)
    await db.flush()
    clear_tenant_cache()
    return await get_tenant_detail(db, slug)


async def suspend_tenant(
    db: AsyncSession,
    slug: str,
    payload: SuspendTenantRequest,
    *,
    actor_email: str,
) -> Optional[ProvisioningJob]:
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        return None
    row.is_active = False
    row.suspended_at = datetime.now(timezone.utc)
    await db.flush()
    clear_tenant_cache()

    job = ProvisioningJob(
        tenant_slug=slug,
        actor_email=actor_email,
        job_type=ProvisioningJobType.SUSPEND.value,
        status=ProvisioningJobStatus.SUCCESS.value,
        completed_at=datetime.now(timezone.utc),
        request_payload={"reason": payload.reason},
    )
    db.add(job)
    await db.flush()
    return job


async def resume_tenant(
    db: AsyncSession,
    slug: str,
    *,
    actor_email: str,
) -> Optional[ProvisioningJob]:
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        return None
    row.is_active = True
    row.suspended_at = None
    await db.flush()
    clear_tenant_cache()

    job = ProvisioningJob(
        tenant_slug=slug,
        actor_email=actor_email,
        job_type=ProvisioningJobType.RESUME.value,
        status=ProvisioningJobStatus.SUCCESS.value,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


async def destroy_tenant(
    db: AsyncSession,
    slug: str,
    payload: DestroyTenantRequest,
    *,
    actor_email: str,
) -> Optional[ProvisioningJob]:
    """Mark tenant inactive + spawn a DESTROY ProvisioningJob that the
    Celery worker dispatches to ``offboard-client.yml`` (mirror of the
    create flow). The actual teardown — drop namespace, delete AWS
    secrets, drop tenant DB/role, remove GitOps files — runs inside the
    workflow's 5 phases and reports progress back via the same signed
    webhook the Console UI already consumes for onboards.

    Raises ``ValueError("confirmation_failed")`` if the caller did not
    provide the right confirmation phrase or slug.
    """
    if payload.confirmation_slug != slug:
        raise ValueError("confirmation_failed")
    if payload.confirmation_phrase != _DESTROY_CONFIRMATION_PHRASE:
        raise ValueError("confirmation_failed")

    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        return None
    # Soft delete; the registry row stays so audit history remains
    # linkable. ``suspended_at`` doubles as "destroyed at". The hard
    # teardown — namespace, secrets, DB — happens in the workflow.
    row.is_active = False
    row.suspended_at = datetime.now(timezone.utc)
    await db.flush()
    clear_tenant_cache()

    # Pending job: the Celery worker will dispatch the workflow on the
    # next tick and flip it to RUNNING once GH ack's the dispatch.
    job = ProvisioningJob(
        tenant_slug=slug,
        actor_email=actor_email,
        job_type=ProvisioningJobType.DESTROY.value,
        status=ProvisioningJobStatus.PENDING.value,
        request_payload={"confirmation_slug": payload.confirmation_slug},
    )
    db.add(job)
    await db.flush()

    # Dispatch the offboard workflow out-of-band. Import inline to
    # avoid a circular import between services/ and workers/.
    try:
        from src.workers.provisioning_worker import (
            destroy_tenant_via_gh_actions,
        )
        destroy_tenant_via_gh_actions.delay(str(job.id))
    except Exception:  # pragma: no cover — Celery broker / import
        # Don't block the API response on broker hiccups; the job row
        # is already PENDING and an operator can re-dispatch from the
        # Console (or a Celery beat reaper will pick it up).
        logger.exception(
            "destroy_tenant: failed to enqueue offboard task for %s", slug
        )

    return job


# ── Dashboard / audit / jobs ───────────────────────────────────────


async def dashboard_summary(db: AsyncSession) -> DashboardSummary:
    total = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    active = (
        await db.execute(
            select(func.count()).select_from(Tenant).where(Tenant.is_active == True)  # noqa: E712
        )
    ).scalar_one()
    suspended = total - active

    by_tier_rows = (
        await db.execute(
            select(Tenant.tier, func.count()).group_by(Tenant.tier)
        )
    ).all()
    by_tier: Dict[str, int] = {tier: count for tier, count in by_tier_rows}

    recent = (
        await db.execute(
            select(InternalConsoleAudit)
            .order_by(InternalConsoleAudit.timestamp.desc())
            .limit(20)
        )
    ).scalars().all()

    return DashboardSummary(
        total_tenants=total,
        active_tenants=active,
        suspended_tenants=suspended,
        tenants_by_tier=by_tier,
        recent_audit=[AuditEntryRead.model_validate(r) for r in recent],
    )


async def list_audit(
    db: AsyncSession,
    *,
    tenant_slug: Optional[str] = None,
    actor_email: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[AuditEntryRead]:
    stmt = select(InternalConsoleAudit)
    if tenant_slug:
        stmt = stmt.where(InternalConsoleAudit.tenant_slug == tenant_slug)
    if actor_email:
        stmt = stmt.where(
            func.lower(InternalConsoleAudit.actor_email) == actor_email.lower()
        )
    stmt = stmt.order_by(InternalConsoleAudit.timestamp.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditEntryRead.model_validate(r) for r in rows]


async def list_jobs(
    db: AsyncSession,
    *,
    tenant_slug: Optional[str] = None,
    limit: int = 100,
) -> List[ProvisioningJobRead]:
    stmt = select(ProvisioningJob)
    if tenant_slug:
        stmt = stmt.where(ProvisioningJob.tenant_slug == tenant_slug)
    stmt = stmt.order_by(ProvisioningJob.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ProvisioningJobRead.model_validate(r) for r in rows]


async def rerun_job(
    db: AsyncSession,
    job_id: str,
    *,
    actor_email: str,
) -> ProvisioningJob:
    """Re-run the failed jobs of a provisioning workflow on GitHub.

    Mirrors the GitHub UI ``Re-run failed jobs`` button:

    1. Validates the job exists, is in ``FAILED`` state, and has an
       ``external_run_id`` (i.e. the dispatch reached GH originally).
    2. Calls ``POST /actions/runs/{id}/rerun-failed-jobs`` on the
       GitHub API. Only the failed steps re-execute; the green phases
       from the original run carry over.
    3. Resets the ``ProvisioningJob`` row back to ``PENDING`` so the
       Console UI shows it as live again. The reconciler in the worker
       will pick it up and re-converge ``status`` from the GH API once
       the re-run finishes.

    Raises ``ValueError`` for the route to translate to HTTP errors:
    - ``not_found``           — no such job_id
    - ``not_failed``          — only failed jobs can be re-run
    - ``no_external_run``     — dispatch never landed; nothing to re-run
    - ``rerun_disabled``      — GH_PROVISIONING_TOKEN is unset
    - ``gh_api: <status>``    — GitHub API returned non-2xx
    """
    import os
    import uuid as _uuid
    import httpx

    try:
        job_uuid = _uuid.UUID(job_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("not_found") from exc

    row = (
        await db.execute(select(ProvisioningJob).where(ProvisioningJob.id == job_uuid))
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("not_found")

    if row.status != ProvisioningJobStatus.FAILED.value:
        raise ValueError("not_failed")
    if not row.external_run_id:
        raise ValueError("no_external_run")

    # Lazy-import the GH constants from the worker to keep one source
    # of truth for owner / repo / token env var names.
    from src.workers.provisioning_worker import (
        DEFAULT_OWNER,
        DEFAULT_REPO,
        GH_API_BASE,
        GH_OWNER_ENV,
        GH_REPO_ENV,
        GH_TOKEN_ENV,
        _gh_headers,
        reconcile_provisioning_job,
    )

    token = os.getenv(GH_TOKEN_ENV) or ""
    if not token:
        raise ValueError("rerun_disabled")
    owner = os.getenv(GH_OWNER_ENV) or DEFAULT_OWNER
    repo = os.getenv(GH_REPO_ENV) or DEFAULT_REPO

    url = (
        f"{GH_API_BASE}/repos/{owner}/{repo}/actions/runs/"
        f"{row.external_run_id}/rerun-failed-jobs"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=_gh_headers(token))
    except Exception as exc:
        raise ValueError(f"gh_api: {exc}") from exc
    if response.status_code >= 300:
        raise ValueError(f"gh_api: {response.status_code} {response.text[:200]}")

    # Reset BE state so the Console shows the job as live again. The
    # reconciler will then poll the GH API and converge the final
    # status as the rerun completes. ``actor_email`` is recorded on
    # the new error_message so the audit trail captures who triggered
    # the rerun even before we wire it into the AuditAction enum.
    row.status = ProvisioningJobStatus.PENDING.value
    row.completed_at = None
    prior_error = row.error_message or ""
    row.error_message = f"(rerun by {actor_email}; previous: {prior_error[:200]})"
    await db.flush()

    try:
        reconcile_provisioning_job.apply_async(
            args=[str(row.id)],
            countdown=20,
        )
    except Exception as exc:
        logger.warning("rerun_job: could not schedule reconciler: %s", exc)

    return row


async def mark_job_operational(
    db: AsyncSession,
    job_id: str,
    *,
    actor_email: str,
) -> ProvisioningJob:
    """Mark a failed provisioning job as operationally healthy.

    Use when the underlying GH Actions run ended in failure but an
    operator verified that the tenant is actually live and reachable —
    for example the migrate Job ran longer than the workflow's wait
    timeout (so the workflow marked it failed) but alembic actually
    finished successfully and the remaining steps were applied by
    hand. The job's history stays intact; we just flip ``status`` to
    ``manually_completed`` so the Console renders the tenant as live
    and append a synthetic event with the actor for the audit trail.

    Raises ``ValueError``:
    - ``not_found``           — no such job_id
    - ``not_failed``          — only failed jobs can be marked
    - ``already_completed``   — job is already marked manually_completed
    """
    import uuid as _uuid

    try:
        job_uuid = _uuid.UUID(job_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("not_found") from exc

    row = (
        await db.execute(select(ProvisioningJob).where(ProvisioningJob.id == job_uuid))
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("not_found")
    if row.status == ProvisioningJobStatus.MANUALLY_COMPLETED.value:
        raise ValueError("already_completed")
    if row.status != ProvisioningJobStatus.FAILED.value:
        raise ValueError("not_failed")

    row.status = ProvisioningJobStatus.MANUALLY_COMPLETED.value
    if row.completed_at is None:
        row.completed_at = func.now()

    # Append an audit event so the timeline shows the manual sign-off.
    from src.models.internal_console import ProvisioningJobEvent

    event = ProvisioningJobEvent(
        job_id=row.id,
        phase="report",
        status="succeeded",
        level="info",
        message=f"Marked operational by {actor_email}",
        event_metadata={"actor_email": actor_email, "via": "mark_operational"},
    )
    db.add(event)
    await db.flush()
    return row


# ── Helpers ────────────────────────────────────────────────────────


def _safe_pct(used: Any, limits: Any, key: str) -> float:
    used_val = (used or {}).get(key, 0) if isinstance(used, dict) else 0
    limit_val = (limits or {}).get(key, 0) if isinstance(limits, dict) else 0
    if not limit_val:
        return 0.0
    try:
        return round(100.0 * float(used_val) / float(limit_val), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _pct_from_plan(plan: Optional[TenantPlanLimits], dim: str) -> float:
    """Compute usage % from a TenantPlanLimits row.

    dim values:
      "agents"  → current_agents / max_agents
      "users"   → current_users / max_users   (mapped to Sources % in the UI)
      "storage" → current_storage_bytes / (max_storage_gb * 1 GiB)
    NULL ceiling (enterprise unlimited) returns 0.0 — UI renders "—".
    """
    if plan is None:
        return 0.0
    try:
        if dim == "agents":
            used, limit = plan.current_agents or 0, plan.max_agents
        elif dim == "users":
            used, limit = plan.current_users or 0, plan.max_users
        elif dim == "storage":
            used = plan.current_storage_bytes or 0
            limit = (plan.max_storage_gb * 1_073_741_824) if plan.max_storage_gb else None
        else:
            return 0.0
        if not limit:
            return 0.0
        return round(100.0 * float(used) / float(limit), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _health_score_from_plan(plan: Optional[TenantPlanLimits]) -> int:
    """Compute a 0-100 health score from live plan counters.

    Weights:
      40% — agent adoption (agents created vs. cap)
      60% — platform activity (queries this month vs. cap)
    Unlimited tiers (max=None) score full weight for that dimension
    as soon as any usage exists.
    """
    if plan is None:
        return 0
    score = 0.0
    agents_used = plan.current_agents or 0
    queries_used = plan.current_queries_this_month or 0

    if plan.max_agents:
        score += 40.0 * min(1.0, agents_used / plan.max_agents)
    elif agents_used > 0:
        score += 40.0

    if plan.max_queries_per_month:
        score += 60.0 * min(1.0, queries_used / plan.max_queries_per_month)
    elif queries_used > 0:
        score += 60.0

    return min(100, int(score))


def _is_unlimited(plan: Optional[TenantPlanLimits]) -> bool:
    """True when the plan has no capacity ceiling on any dimension."""
    if plan is None:
        return False
    return plan.max_agents is None and plan.max_users is None and plan.max_storage_gb is None
