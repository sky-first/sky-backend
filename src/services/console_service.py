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

    ``capacity_pct_*`` fields are computed from ``capacity_used`` over
    ``capacity_limits``. A limit of zero means "no limit" for that
    dimension — display as 0%.
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

    items = [
        ConsoleTenantSummary(
            slug=row.slug,
            display_name=row.display_name,
            tier=row.tier,
            is_active=row.is_active,
            suspended_at=row.suspended_at,
            custom_domain=row.custom_domain,
            created_at=row.created_at,
            capacity_pct_agents=_safe_pct(row.capacity_used, row.capacity_limits, "agents"),
            capacity_pct_sources=_safe_pct(row.capacity_used, row.capacity_limits, "sources"),
            capacity_pct_indexed_gb=_safe_pct(
                row.capacity_used, row.capacity_limits, "indexed_gb"
            ),
        )
        for row in rows
    ]
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
    """Soft-destroy: set is_active=false, write DESTROY job. Real
    teardown (drop pods, delete secrets) happens out-of-band in v1.1.

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
    # Soft delete; the row stays in the registry so audit history
    # remains linkable. ``suspended_at`` doubles as "destroyed at".
    row.is_active = False
    row.suspended_at = datetime.now(timezone.utc)
    await db.flush()
    clear_tenant_cache()

    job = ProvisioningJob(
        tenant_slug=slug,
        actor_email=actor_email,
        job_type=ProvisioningJobType.DESTROY.value,
        status=ProvisioningJobStatus.SUCCESS.value,
        completed_at=datetime.now(timezone.utc),
        request_payload={"confirmation_slug": payload.confirmation_slug},
    )
    db.add(job)
    await db.flush()
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
