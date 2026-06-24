"""Internal Console REST API (Projeto B B#2).

Mounted at ``/api/console/v1`` (instead of ``/api/v1/console``) per the
spec — the Console traffic is operationally separate from customer
traffic and the distinct prefix lets us add a separate rate-limit
bucket later.

Every route here goes through :func:`require_sky_team` so unauthorised
callers get a 403 before any handler logic runs. Write routes call
:func:`audit_action` explicitly at the end so the audit log captures
actor + payload even when the request fails. We use direct calls
rather than a decorator because the latter clashes with FastAPI's
Pydantic body inspection (the wrapper hides the original signature).
"""

from __future__ import annotations

from typing import List, Optional

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from src.api.console_auth import (
    audit_action,
    require_sky_team,
    role_for,
)
from src.api.deps import get_db_session
from src.models.internal_console import AuditAction, AuditResult
from src.models.tenant import Tenant
from src.models.tenant_plan_limits import TIER_LIMITS, TenantPlanLimits
from src.models.user import User
from src.models.internal_console import ConsoleRole
from src.schemas.internal_console import (
    AlertsResponse,
    AuditEntryRead,
    ChangeTierRequest,
    ComplianceRead,
    ComplianceSummary,
    ComplianceUpdate,
    ConsoleMeResponse,
    ConsoleTenantDetail,
    ConsoleTenantList,
    CostBreakdownModel,
    CreateRoleGrantRequest,
    CreateTenantRequest,
    CSMNotesRead,
    CSMNotesUpdate,
    DashboardActivityResponse,
    DashboardSummary,
    DestroyTenantRequest,
    IncidentsResponse,
    InfraResponse,
    LlmByModelRow,
    LlmMetricsResponse,
    MyAccessResponse,
    PlatformHealthResponse,
    ProvisioningJobListResponse,
    ProvisioningJobRead,
    RenewalEntry,
    RenewalsResponse,
    RevenueSummaryResponse,
    RoleGrantRead,
    RoleGrantsListResponse,
    SuspendTenantRequest,
    TenantActivityResponse,
    TenantBillingResponse,
    TenantDbConfigRead,
    TenantDbConfigTestResult,
    TenantDbConfigUpdate,
    TenantHealthResponse,
    TierPresetResponse,
    UpdateCapacityLimitsRequest,
    UpdateTenantRequest,
)
from src.models.internal_console import (
    ConsoleImpersonationSession,
    ConsoleSupportTicket,
    ConsoleTenantCompliance,
    InternalConsoleAudit,
    ProvisioningJob,
)
from src.schemas.internal_console import (
    BoardPackResponse,
    ImpersonationSessionRead,
    ImpersonationStartRequest,
    Notification,
    NotificationsResponse,
    SupportTicketCreate,
    SupportTicketRead,
    SupportTicketUpdate,
    SupportTicketsList,
    TenantCompareEntry,
    TenantCompareResponse,
)
from src.config.settings import settings
from src.services import (
    console_rbac,
    console_service,
    csm_service,
    pricing_service,
    pricing_tiers,
)
from src.services.console_telemetry import (
    TelemetryUnavailable,
    activity_provider,
    billing_provider,
    cost_provider,
    infra_provider,
)

router = APIRouter()


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _impersonation_read(row: "ConsoleImpersonationSession") -> "ImpersonationSessionRead":
    """Build the read schema with the computed TTL fields populated.

    Gap #6 fix: the row itself doesn't (yet) carry ``expires_at`` —
    compute it from ``started_at + IMPERSONATION_TTL`` and roll status
    into one of ``active`` / ``expired`` / ``ended`` so the UI doesn't
    repeat the date math.
    """
    from src.core.impersonation_ttl import compute_expires_at, status_for

    obj = ImpersonationSessionRead.model_validate(row)
    obj.expires_at = compute_expires_at(row.started_at)
    obj.status = status_for(row)
    return obj


# ── Me ─────────────────────────────────────────────────────────────


@router.get("/me", response_model=ConsoleMeResponse, summary="Current Sky-team member")
async def get_me(user: User = Depends(require_sky_team)) -> ConsoleMeResponse:
    return ConsoleMeResponse(
        email=user.email,
        role=role_for(user),
        is_sky_team=True,
    )


# ── Dashboard ──────────────────────────────────────────────────────


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardSummary:
    summary = await console_service.dashboard_summary(db)
    await audit_action(
        db,
        actor=user,
        action=AuditAction.VIEW_DASHBOARD,
        tenant_slug=None,
        result=AuditResult.SUCCESS,
        actor_ip=_ip(request),
    )
    return summary


@router.get(
    "/ceo",
    summary="CEO Master Dashboard",
    description=(
        "Aggregated business view: contracted ARR / MRR, last-month "
        "infra cost (annualised → margin), per-tier distribution, "
        "churn / over-cap signals and provisioning pipeline health. "
        "Single read endpoint — every sub-aggregate runs against the "
        "same session so the snapshot is internally consistent."
    ),
)
async def get_ceo_dashboard(
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
):
    from src.schemas.internal_console import (
        CeoChurnSignal as CeoChurnSignalSchema,
        CeoMasterSummaryResponse,
        CeoProvisioningHealth as CeoProvisioningHealthSchema,
        CeoTierRow as CeoTierRowSchema,
    )
    from src.services.ceo_dashboard import compute_ceo_summary

    summary = await compute_ceo_summary(db)
    await audit_action(
        db,
        actor=user,
        action=AuditAction.VIEW_DASHBOARD,
        tenant_slug=None,
        result=AuditResult.SUCCESS,
        result_details={"view": "ceo"},
        actor_ip=_ip(request),
    )
    return CeoMasterSummaryResponse(
        computed_at=summary.computed_at,
        total_tenants=summary.total_tenants,
        active_tenants=summary.active_tenants,
        suspended_tenants=summary.suspended_tenants,
        contracted_arr_eur=summary.contracted_arr_eur,
        contracted_mrr_eur=summary.contracted_mrr_eur,
        last_month_cost_eur=summary.last_month_cost_eur,
        gross_margin_pct=summary.gross_margin_pct,
        tiers=[CeoTierRowSchema(**vars(t)) for t in summary.tiers],
        churn_signals=[CeoChurnSignalSchema(**vars(s)) for s in summary.churn_signals],
        provisioning=CeoProvisioningHealthSchema(**vars(summary.provisioning)),
        llm_cost_30d_eur=getattr(summary, "llm_cost_30d_eur", None),
    )


# ── Tenants ────────────────────────────────────────────────────────


@router.get("/tenants", response_model=ConsoleTenantList)
async def list_tenants(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    tier: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ConsoleTenantList:
    return await console_service.list_tenants(
        db, tier=tier, is_active=is_active, search=search, limit=limit, offset=offset
    )


@router.get("/tenants/{slug}", response_model=ConsoleTenantDetail)
async def get_tenant(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ConsoleTenantDetail:
    detail = await console_service.get_tenant_detail(db, slug)
    if detail is None:
        await audit_action(
            db,
            actor=user,
            action=AuditAction.VIEW_TENANT,
            tenant_slug=slug,
            result=AuditResult.FAILURE,
            result_details={"reason": "not_found"},
            actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")
    await audit_action(
        db,
        actor=user,
        action=AuditAction.VIEW_TENANT,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        actor_ip=_ip(request),
    )
    return detail


@router.post(
    "/tenants",
    response_model=ConsoleTenantDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    request: Request,
    payload: CreateTenantRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ConsoleTenantDetail:
    try:
        detail, _job = await console_service.create_tenant(
            db, payload, actor_email=user.email
        )
    except ValueError as exc:
        if str(exc) == "slug_taken":
            await audit_action(
                db,
                actor=user,
                action=AuditAction.CREATE_TENANT,
                tenant_slug=payload.slug,
                result=AuditResult.FAILURE,
                result_details={"reason": "slug_taken"},
                actor_ip=_ip(request),
            )
            raise HTTPException(status_code=409, detail="Tenant slug already taken")
        raise
    await audit_action(
        db,
        actor=user,
        action=AuditAction.CREATE_TENANT,
        tenant_slug=payload.slug,
        result=AuditResult.SUCCESS,
        request_payload=_redact(payload.model_dump()),
        actor_ip=_ip(request),
    )
    return detail


@router.patch("/tenants/{slug}", response_model=ConsoleTenantDetail)
async def update_tenant(
    slug: str,
    request: Request,
    payload: UpdateTenantRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ConsoleTenantDetail:
    detail = await console_service.update_tenant(db, slug, payload)
    if detail is None:
        await audit_action(
            db,
            actor=user,
            action=AuditAction.UPDATE_TENANT,
            tenant_slug=slug,
            result=AuditResult.FAILURE,
            result_details={"reason": "not_found"},
            actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")
    await audit_action(
        db,
        actor=user,
        action=AuditAction.UPDATE_TENANT,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload=_redact(payload.model_dump(exclude_unset=True)),
        actor_ip=_ip(request),
    )
    return detail


@router.post(
    "/tenants/{slug}/suspend",
    response_model=ProvisioningJobRead,
)
async def suspend_tenant(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    payload: SuspendTenantRequest = Body(default_factory=SuspendTenantRequest),
) -> ProvisioningJobRead:
    job = await console_service.suspend_tenant(
        db, slug, payload, actor_email=user.email
    )
    if job is None:
        await audit_action(
            db, actor=user, action=AuditAction.SUSPEND_TENANT,
            tenant_slug=slug, result=AuditResult.FAILURE,
            result_details={"reason": "not_found"}, actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")
    await audit_action(
        db, actor=user, action=AuditAction.SUSPEND_TENANT,
        tenant_slug=slug, result=AuditResult.SUCCESS,
        request_payload=payload.model_dump(), actor_ip=_ip(request),
    )
    return ProvisioningJobRead.model_validate(job)


@router.post(
    "/tenants/{slug}/resume",
    response_model=ProvisioningJobRead,
)
async def resume_tenant(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ProvisioningJobRead:
    job = await console_service.resume_tenant(db, slug, actor_email=user.email)
    if job is None:
        await audit_action(
            db, actor=user, action=AuditAction.RESUME_TENANT,
            tenant_slug=slug, result=AuditResult.FAILURE,
            result_details={"reason": "not_found"}, actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")
    await audit_action(
        db, actor=user, action=AuditAction.RESUME_TENANT,
        tenant_slug=slug, result=AuditResult.SUCCESS, actor_ip=_ip(request),
    )
    return ProvisioningJobRead.model_validate(job)


@router.post(
    "/tenants/{slug}/destroy",
    response_model=ProvisioningJobRead,
)
async def destroy_tenant(
    slug: str,
    request: Request,
    payload: DestroyTenantRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ProvisioningJobRead:
    try:
        job = await console_service.destroy_tenant(
            db, slug, payload, actor_email=user.email
        )
    except ValueError as exc:
        if str(exc) == "confirmation_failed":
            await audit_action(
                db, actor=user, action=AuditAction.DESTROY_TENANT,
                tenant_slug=slug, result=AuditResult.FAILURE,
                result_details={"reason": "confirmation_failed"},
                actor_ip=_ip(request),
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "confirmation_failed",
                    "detail": (
                        "Provide the slug exactly as it appears and the "
                        "phrase 'I understand this is irreversible'."
                    ),
                },
            )
        raise
    if job is None:
        await audit_action(
            db, actor=user, action=AuditAction.DESTROY_TENANT,
            tenant_slug=slug, result=AuditResult.FAILURE,
            result_details={"reason": "not_found"}, actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")
    await audit_action(
        db, actor=user, action=AuditAction.DESTROY_TENANT,
        tenant_slug=slug, result=AuditResult.SUCCESS,
        actor_ip=_ip(request),
    )
    return ProvisioningJobRead.model_validate(job)


# ── Audit + jobs ───────────────────────────────────────────────────


@router.get("/audit", response_model=List[AuditEntryRead])
async def list_audit(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    tenant_slug: Optional[str] = Query(None, max_length=50),
    actor_email: Optional[str] = Query(None, max_length=255),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[AuditEntryRead]:
    return await console_service.list_audit(
        db,
        tenant_slug=tenant_slug,
        actor_email=actor_email,
        limit=limit,
        offset=offset,
    )


@router.get("/health", summary="Console API liveness check")
async def health_check(
    _: User = Depends(require_sky_team),
) -> dict:
    return {"status": "ok", "version": settings.APP_VERSION}


@router.get("/jobs", response_model=List[ProvisioningJobRead])
async def list_jobs(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    tenant_slug: Optional[str] = Query(None, max_length=50),
    limit: int = Query(100, ge=1, le=500),
) -> List[ProvisioningJobRead]:
    return await console_service.list_jobs(db, tenant_slug=tenant_slug, limit=limit)


@router.get(
    "/tenants/{slug}/status",
    summary="Latest provisioning status for a tenant",
)
async def get_tenant_provisioning_status(
    slug: str,
    _: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Returns whether the tenant exists and the most recent provisioning job."""
    tenant_q = await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    exists = tenant_q.scalar_one_or_none() is not None
    jobs = await console_service.list_jobs(db, tenant_slug=slug, limit=1)
    last_job = jobs[0] if jobs else None
    return {
        "tenant_slug": slug,
        "exists": exists,
        "last_job": last_job.model_dump() if last_job else None,
    }


@router.get(
    "/tenants/{slug}/runs",
    response_model=ProvisioningJobListResponse,
    summary="Provisioning run history for a tenant",
)
async def list_tenant_runs(
    slug: str,
    _: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(20, ge=1, le=100),
) -> ProvisioningJobListResponse:
    tenant_q = await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    if tenant_q.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    items = await console_service.list_jobs(db, tenant_slug=slug, limit=limit)
    return ProvisioningJobListResponse(items=items, total=len(items))


@router.post(
    "/jobs/{job_id}/rerun",
    response_model=ProvisioningJobRead,
    summary="Re-run failed jobs of a provisioning workflow run (GitHub-Actions style)",
)
async def rerun_job(
    job_id: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ProvisioningJobRead:
    """Retry a failed provisioning job by re-running only the failed
    GitHub Actions jobs on its workflow run.

    Mirrors the GitHub UI's ``Re-run failed jobs`` button — cheaper than
    spawning a brand-new workflow because successful phases (preflight,
    plan, ...) don't repeat, only the broken one does.
    """
    try:
        job = await console_service.rerun_job(db, job_id, actor_email=user.email)
    except ValueError as exc:
        msg = str(exc)
        if msg in ("not_found",):
            raise HTTPException(status_code=404, detail="job not found")
        if msg in ("not_failed", "no_external_run", "rerun_disabled"):
            raise HTTPException(status_code=409, detail=msg)
        if msg.startswith("gh_api:"):
            raise HTTPException(
                status_code=502,
                detail={"error": "github_api", "detail": msg},
            )
        raise HTTPException(status_code=400, detail=msg)

    # NOTE: audit logging for rerun deferred until a follow-up migration
    # adds ``RERUN_JOB`` to the AuditAction enum + CHECK constraint.
    # The job state mutation itself is observable via the new
    # provisioning_job_events row that lands on the next phase event.
    return ProvisioningJobRead.model_validate(job)


@router.post(
    "/jobs/{job_id}/mark-operational",
    response_model=ProvisioningJobRead,
    summary="Mark a provisioning job as manually completed",
    description=(
        "Use when the workflow itself ended in failure but the tenant is "
        "actually live and reachable — e.g. the migrate Job took longer "
        "than the workflow's wait but the alembic upgrade succeeded, and "
        "an operator finished the remaining steps by hand. Sets the job "
        "status to ``manually_completed`` and appends a synthetic event "
        "with the actor's name so the audit trail tells the truth."
    ),
)
async def mark_job_operational(
    job_id: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ProvisioningJobRead:
    try:
        job = await console_service.mark_job_operational(
            db, job_id, actor_email=user.email
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "not_found":
            raise HTTPException(status_code=404, detail="job not found")
        if msg in ("already_completed", "not_failed"):
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return ProvisioningJobRead.model_validate(job)


# ── Local helpers ──────────────────────────────────────────────────


_REDACT_KEYS = {"password", "secret", "token", "authorization"}


def _redact(payload: dict) -> dict:
    return {
        k: ("***REDACTED***" if k.lower() in _REDACT_KEYS else v)
        for k, v in payload.items()
    }


# ── Pricing tiers (B#16) ───────────────────────────────────────────


@router.get("/tiers", response_model=List[TierPresetResponse])
async def list_pricing_tiers(
    user: User = Depends(require_sky_team),
) -> List[TierPresetResponse]:
    return [TierPresetResponse(**t.__dict__) for t in pricing_tiers.list_tiers()]


# Map of Console product-tier slug → commercial tier slug used by
# ``tenant_plan_limits``. Until Fase 3 reconciles the two naming
# systems, the Console drives the product-tier label (registry) and
# also moves the plan-limits row onto the closest commercial tier so
# the runtime enforcement hooks (agents/users/storage/queries) line up
# with what the customer is paying for. ``core`` and ``advanced`` both
# map to ``scale`` because the enforced commercial ceilings are the
# same band; ``strategic`` maps to ``enterprise`` (unlimited).
_REGISTRY_TO_COMMERCIAL_TIER: dict[str, str] = {
    "starter": "starter",
    "foundation": "foundation",
    "core": "scale",
    "advanced": "scale",
    "strategic": "enterprise",
}


# Conversion factor used for the storage breach comparison. The plan-
# limits row stores ``current_storage_bytes`` (atomic increments) and
# ``max_storage_gb`` (human-readable ceiling); the breach payload
# reports the used value in GB so the operator UI matches the cap unit.
_BYTES_PER_GB = 1024 * 1024 * 1024


async def _plan_limits_breaches(
    db: AsyncSession,
    tenant_id,
    new_commercial_tier: str,
) -> list[dict]:
    """Return per-dimension breaches against ``tenant_plan_limits``.

    Gap #4 (2026-05-30): the legacy ``capacity_used`` check on
    ``Tenant.capacity_used`` can be stale (it's bookkept by a daily
    job), so the canonical Fase-1 enforcement counters live on
    ``tenant_plan_limits.current_*``. We consult both sources on a
    downgrade and merge the breaches — a customer over the cap on
    EITHER source is refused.

    Returns an empty list when the target tier is Enterprise (all
    ceilings NULL = unlimited) or when the tenant has no plan-limits
    row yet (treated as zero usage — fresh tenant).
    """
    new_caps = TIER_LIMITS.get(new_commercial_tier)
    if new_caps is None:
        return []  # unknown commercial tier — caller already 400'd

    row = await db.get(TenantPlanLimits, tenant_id)
    if row is None:
        # Fresh tenant — no enforcement counters yet. Falling through
        # to the legacy capacity_used check is enough.
        return []

    breaches: list[dict] = []

    def _push(dimension: str, used: int, new_cap: int | None) -> None:
        if new_cap is None:
            return  # unlimited target tier — never a breach
        if used > new_cap:
            breaches.append(
                {
                    "dimension": dimension,
                    "used": int(used),
                    "new_cap": int(new_cap),
                    "excess": int(used - new_cap),
                    "source": "tenant_plan_limits",
                }
            )

    _push("agents", int(row.current_agents or 0), new_caps["max_agents"])
    _push("users", int(row.current_users or 0), new_caps["max_users"])
    # Storage: compare GB-to-GB (round up so 1 byte over a GB still
    # counts — the customer is at GB+1 of consumption, not GB).
    current_gb = (int(row.current_storage_bytes or 0) + _BYTES_PER_GB - 1) // _BYTES_PER_GB
    _push("storage_gb", current_gb, new_caps["max_storage_gb"])
    _push(
        "queries_this_month",
        int(row.current_queries_this_month or 0),
        new_caps["max_queries_per_month"],
    )

    return breaches


@router.post(
    "/tenants/{slug}/tier",
    response_model=ConsoleTenantDetail,
)
async def change_tenant_tier(
    slug: str,
    request: Request,
    payload: ChangeTierRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ConsoleTenantDetail:
    """Move a tenant to a different pricing tier.

    Downgrade safety: when ``apply_preset`` is true and the new tier's
    preset caps would be lower than what the tenant currently
    consumes, we refuse with 422 and return a per-dimension breakdown
    of which resources exceed the target. The operator can either:

      * free capacity on the tenant side (delete agents/sources) and
        retry, or
      * pass ``apply_preset=false`` to flip the label only, leaving the
        existing ``capacity_limits`` intact (the contractual-override
        path — used when a customer pays Starter but has a carved-out
        higher cap negotiated in the contract).

    Idempotency: setting the tier to the value it already has is a
    no-op for the audit log but still re-applies the preset caps when
    ``apply_preset`` is true, so the operator can use this endpoint as
    "reset capacity limits to preset" too.

    Gap #4 (2026-05-30): the downgrade check now consults BOTH
    ``Tenant.capacity_used`` (legacy bookkeeping JSONB) and
    ``tenant_plan_limits.current_*`` (canonical Fase-1 enforcement
    counters). Either source over the new cap → 422. On success we
    also push the new tier into ``tenant_plan_limits`` so the hot-path
    hooks pick up the new ceilings.
    """
    preset = pricing_tiers.get_tier(payload.tier)
    if preset is None:
        raise HTTPException(status_code=400, detail="Unknown tier")
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # ── Downgrade safety check (Gap #4, 2026-05-30) ────────────────
    # Only enforce when the operator asked us to apply the preset;
    # ``apply_preset=false`` is the explicit "keep contractual
    # override" path and bypasses the check on purpose.
    #
    # We now consult TWO sources and merge their breaches:
    #
    #   1. ``Tenant.capacity_used`` — legacy JSONB updated by a daily
    #      bookkeeping job. Keyed by ``agents``/``sources``/``indexed_gb``
    #      and compared against ``preset.capacity_limits`` (registry
    #      side, product tier).
    #
    #   2. ``tenant_plan_limits.current_*`` — Fase 1 canonical counters
    #      bumped atomically from the hot paths (every agent/user
    #      create, every AI query). Compared against ``TIER_LIMITS``
    #      for the mapped commercial tier.
    #
    # Either source over the new cap → 422. Each breach carries a
    # ``source`` field so the operator can tell which counter tripped
    # and (if needed) reconcile a desync between the two.
    new_commercial_tier = _REGISTRY_TO_COMMERCIAL_TIER.get(preset.slug)
    if payload.apply_preset:
        used = row.capacity_used or {}
        breaches: list[dict] = []
        for dim, new_cap in preset.capacity_limits.items():
            current_used = int(used.get(dim, 0) or 0)
            if current_used > int(new_cap):
                breaches.append(
                    {
                        "dimension": dim,
                        "used": current_used,
                        "new_cap": int(new_cap),
                        "excess": current_used - int(new_cap),
                        "source": "capacity_used",
                    }
                )

        # Plan-limits source. Skipped when the registry tier doesn't
        # have a commercial mapping (defensive — every tier in
        # TIER_REGISTRY is mapped above, but keep the guard so a future
        # tier add doesn't accidentally bypass enforcement).
        if new_commercial_tier is not None:
            breaches.extend(
                await _plan_limits_breaches(
                    db, row.id, new_commercial_tier
                )
            )

        if breaches:
            await audit_action(
                db,
                actor=user,
                action=AuditAction.CHANGE_TIER,
                tenant_slug=slug,
                result=AuditResult.FAILURE,
                request_payload={
                    "from": row.tier,
                    "to": preset.slug,
                    "apply_preset": True,
                    "reason": "downgrade_exceeds_new_caps",
                    "breaches": breaches,
                    "intent": "tier_change_with_plan_limits",
                },
                actor_ip=_ip(request),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "tier_change_breach",
                    "message": (
                        f"Tenant {slug!r} currently consumes more than the "
                        f"{preset.slug!r} tier allows. Free capacity or pass "
                        f"apply_preset=false to keep the override."
                    ),
                    "from_tier": row.tier,
                    "to_tier": preset.slug,
                    "breaches": breaches,
                },
            )

    old_tier = row.tier
    tier_actually_changed = old_tier != preset.slug
    row.tier = preset.slug
    row.rate_limit_rpm = preset.rate_limit_rpm
    row.rate_limit_tpm = preset.rate_limit_tpm
    if payload.apply_preset:
        row.capacity_limits = dict(preset.capacity_limits)
    await db.flush()

    # ── Sync tenant_plan_limits (Gap #4, 2026-05-30) ───────────────
    # After a successful tier change with ``apply_preset=true``, update
    # the Fase-1 plan-limits row so the hot-path enforcement hooks
    # (agents/users/storage/queries) see the new ceilings. We call
    # ``pricing_service.set_tier`` rather than UPDATE'ing the row by
    # hand — it owns the threshold-alert reset semantics. Counters
    # carry over by design (the customer's existing consumption isn't
    # zeroed when they switch tier).
    #
    # ``apply_preset=false`` keeps the existing plan-limits row
    # untouched: that path is the "contractual override" — the operator
    # is flipping the label only.
    if payload.apply_preset and new_commercial_tier is not None:
        await pricing_service.set_tier(
            db, new_commercial_tier, tenant_id=row.id
        )

    from src.api.middleware.tenant_resolver import clear_tenant_cache

    clear_tenant_cache()

    # Only audit a real tier change. Re-applying the preset onto the
    # same tier doesn't add value to the CHANGE_TIER feed.
    if tier_actually_changed:
        await audit_action(
            db,
            actor=user,
            action=AuditAction.CHANGE_TIER,
            tenant_slug=slug,
            result=AuditResult.SUCCESS,
            request_payload={
                "from": old_tier,
                "to": preset.slug,
                "apply_preset": payload.apply_preset,
                "intent": "tier_change_with_plan_limits",
                "commercial_tier": new_commercial_tier,
            },
            actor_ip=_ip(request),
        )

    detail = await console_service.get_tenant_detail(db, slug)
    assert detail is not None
    return detail


@router.patch(
    "/tenants/{slug}/capacity_limits",
    response_model=ConsoleTenantDetail,
)
async def update_capacity_limits(
    slug: str,
    request: Request,
    payload: UpdateCapacityLimitsRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ConsoleTenantDetail:
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    row.capacity_limits = {
        "agents": payload.agents,
        "sources": payload.sources,
        "indexed_gb": payload.indexed_gb,
    }
    await db.flush()

    from src.api.middleware.tenant_resolver import clear_tenant_cache

    clear_tenant_cache()

    await audit_action(
        db,
        actor=user,
        action=AuditAction.UPDATE_CAPACITY,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload=payload.model_dump(),
        actor_ip=_ip(request),
    )

    detail = await console_service.get_tenant_detail(db, slug)
    assert detail is not None
    return detail


# ── Per-tenant DB / Redis config (GBT deploy, PR #19) ──────────────


# 30 chars covers ``arn:aws:secretsmanager:eu-west-1:`` - enough to
# attribute a change to a region but not to the secret itself.
_AUDIT_SECRET_PREFIX_LEN = 30


def _mask_secret_arn(value: Optional[str]) -> Optional[str]:
    """Replace a Secrets Manager ARN with its first 30 chars + ellipsis."""
    if value is None:
        return None
    if len(value) <= _AUDIT_SECRET_PREFIX_LEN:
        return value
    return value[:_AUDIT_SECRET_PREFIX_LEN] + "..."


def _redact_db_config_payload(changes: dict) -> dict:
    """Build the payload stored in ``InternalConsoleAudit.request_payload``."""
    masked = dict(changes)
    for key in ("db_credentials_secret_arn", "redis_credentials_secret_arn"):
        if key in masked:
            masked[key] = _mask_secret_arn(masked[key])
    return masked


@router.get(
    "/tenants/{slug}/db-config",
    response_model=TenantDbConfigRead,
)
async def get_tenant_db_config(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigRead:
    """Return the 6 connection fields stored on the registry row.

    Read-only; no audit entry (parent ``/tenants/{slug}`` GET writes one).
    """
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantDbConfigRead.model_validate(row)


@router.patch(
    "/tenants/{slug}/db-config",
    response_model=TenantDbConfigRead,
)
async def update_tenant_db_config(
    slug: str,
    request: Request,
    payload: TenantDbConfigUpdate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigRead:
    """Patch any subset of the tenant's data-plane connection details.

    Empty payloads are refused (422). All writes go through one
    transaction and end with ``clear_tenant_cache`` so the resolver
    rebuilds the engine on the next request.

    Audit: ``UPDATE_DB_CONFIG`` is emitted on success and failure.
    Secret ARNs are masked in ``request_payload`` (30-char prefix +
    ellipsis); host/port/name are logged verbatim.

    Does NOT restart the tenant API pods - the FE banner warns the
    operator (open question; see PR description).
    """
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_fields_supplied",
                "detail": "Provide at least one field to update.",
            },
        )

    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        await audit_action(
            db,
            actor=user,
            action=AuditAction.UPDATE_DB_CONFIG,
            tenant_slug=slug,
            result=AuditResult.FAILURE,
            result_details={"reason": "not_found"},
            actor_ip=_ip(request),
        )
        raise HTTPException(status_code=404, detail="Tenant not found")

    previous = {key: getattr(row, key) for key in changes.keys()}

    for key, value in changes.items():
        setattr(row, key, value)
    await db.flush()

    from src.api.middleware.tenant_resolver import clear_tenant_cache

    clear_tenant_cache()

    await audit_action(
        db,
        actor=user,
        action=AuditAction.UPDATE_DB_CONFIG,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload={
            "changed_fields": sorted(changes.keys()),
            "new_values": _redact_db_config_payload(changes),
        },
        result_details={
            "previous_values": _redact_db_config_payload(previous),
        },
        actor_ip=_ip(request),
    )
    return TenantDbConfigRead.model_validate(row)


@router.post(
    "/tenants/{slug}/db-config/test",
    response_model=TenantDbConfigTestResult,
    responses={503: {"model": TenantDbConfigTestResult}},
)
async def test_tenant_db_config(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantDbConfigTestResult:
    """Open a transient connection and run ``SELECT 1``.

    Nothing is persisted regardless of outcome. 503 + ``ok=false``
    on any failure; ``TEST_DB_CONFIG`` audit entry written either way.
    """
    import asyncio
    import time

    from src.config.tenant_connection_manager import (
        TenantConnectionManager,
    )
    from src.core.tenant_context import TenantContext

    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    ctx = TenantContext(
        slug=row.slug,
        id=row.id,
        tier=row.tier,
        display_name=row.display_name,
        db_host=row.db_host,
        db_name=row.db_name,
        db_credentials_secret_arn=row.db_credentials_secret_arn,
    )

    manager = TenantConnectionManager()

    started = time.monotonic()
    error_message: Optional[str] = None
    ok = False
    try:
        from sqlalchemy import text as _text
        from sqlalchemy.ext.asyncio import create_async_engine

        url = manager._build_url(ctx)  # noqa: SLF001
        engine = create_async_engine(
            url,
            pool_pre_ping=False,
            pool_size=1,
            max_overflow=0,
            connect_args={"timeout": 5},
        )
        try:
            # asyncio.timeout() requires Python ≥ 3.11; use wait_for for 3.10 compat.
            async def _probe() -> None:
                async with engine.connect() as conn:
                    result = await conn.execute(_text("SELECT 1"))
                    _ = result.scalar()

            await asyncio.wait_for(_probe(), timeout=8)
            ok = True
        finally:
            await engine.dispose()
    except asyncio.TimeoutError:
        error_message = "Connection attempt timed out after 8s"
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"

    latency_ms = int((time.monotonic() - started) * 1000)

    await audit_action(
        db,
        actor=user,
        action=AuditAction.TEST_DB_CONFIG,
        tenant_slug=slug,
        result=AuditResult.SUCCESS if ok else AuditResult.FAILURE,
        request_payload={
            "target_host": row.db_host,
            "target_db": row.db_name,
        },
        result_details={
            "latency_ms": latency_ms,
            "error": error_message,
        },
        actor_ip=_ip(request),
    )

    result_payload = TenantDbConfigTestResult(
        ok=ok,
        latency_ms=latency_ms,
        error=error_message,
        target_host=row.db_host,
        target_db=row.db_name,
    )
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503, content=result_payload.model_dump()
        )
    return result_payload


# ── CSM notes (B#17) ───────────────────────────────────────────────


@router.get(
    "/tenants/{slug}/csm",
    response_model=CSMNotesRead,
)
async def get_csm_notes(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> CSMNotesRead:
    res = await csm_service.build_csm_response(db, slug)
    if res is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return res


@router.put(
    "/tenants/{slug}/csm",
    response_model=CSMNotesRead,
)
async def update_csm_notes(
    slug: str,
    request: Request,
    payload: CSMNotesUpdate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> CSMNotesRead:
    exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await csm_service.update_notes(db, slug, payload, actor_email=user.email)
    await audit_action(
        db,
        actor=user,
        action=AuditAction.UPDATE_TENANT,
        tenant_slug=slug,
        result=AuditResult.SUCCESS,
        request_payload={
            "csm_update": True,
            "fields": [k for k, v in payload.model_dump().items() if v is not None],
        },
        actor_ip=_ip(request),
    )
    res = await csm_service.build_csm_response(db, slug)
    assert res is not None
    return res


# ── Renewals (B#18) ────────────────────────────────────────────────


@router.get("/renewals", response_model=RenewalsResponse)
async def get_upcoming_renewals(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    days: int = Query(90, ge=1, le=365),
) -> RenewalsResponse:
    items = await csm_service.upcoming_renewals(db, days_ahead=days)
    pipeline = sum(r.monthly_amount_eur * 12 for r in items)
    return RenewalsResponse(items=items, total_pipeline_eur=round(pipeline, 2))


# ── RBAC (It4) ─────────────────────────────────────────────────────


@router.get("/me/access", response_model=MyAccessResponse)
async def my_access(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> MyAccessResponse:
    """Return the caller's roles + the action keys they're allowed.

    Frontend reads ``actions`` to hide / show UI primitives. Backend
    still enforces — this is UX, not security.
    """
    roles = await console_rbac.load_active_roles(db, user.email)
    allowed: list[str] = []
    for action in sorted(console_rbac.PERMISSIONS.keys()):
        if console_rbac.has_permission(roles, action):
            allowed.append(action)
    return MyAccessResponse(
        email=user.email,
        roles=[r.value for r in roles],
        actions=allowed,
    )


@router.get(
    "/role-grants",
    response_model=RoleGrantsListResponse,
)
async def list_role_grants_endpoint(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> RoleGrantsListResponse:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "rbac.read")
    grants = await console_rbac.list_role_grants(db)
    return RoleGrantsListResponse(
        items=[RoleGrantRead.model_validate(g) for g in grants],
        available_roles=[r.value for r in ConsoleRole],
        permission_actions=sorted(console_rbac.PERMISSIONS.keys()),
    )


@router.post(
    "/role-grants",
    response_model=RoleGrantsListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_role_grant(
    request: Request,
    payload: CreateRoleGrantRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> RoleGrantsListResponse:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "rbac.write")
    try:
        role_enum = ConsoleRole(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown role")
    await console_rbac.grant_role(
        db,
        user_email=payload.user_email,
        role=role_enum,
        granted_by=user.email,
    )
    await audit_action(
        db,
        actor=user,
        action=AuditAction.GRANT_ROLE,
        tenant_slug=None,
        result=AuditResult.SUCCESS,
        request_payload={
            "user_email": payload.user_email.lower(),
            "role": role_enum.value,
        },
        actor_ip=_ip(request),
    )
    grants = await console_rbac.list_role_grants(db)
    return RoleGrantsListResponse(
        items=[RoleGrantRead.model_validate(g) for g in grants],
        available_roles=[r.value for r in ConsoleRole],
        permission_actions=sorted(console_rbac.PERMISSIONS.keys()),
    )


# ── Support tickets (It7) ──────────────────────────────────────────


@router.get("/support/tickets", response_model=SupportTicketsList)
async def list_support_tickets(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    tenant_slug: Optional[str] = Query(None, max_length=50),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> SupportTicketsList:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "support.read")
    stmt = select(ConsoleSupportTicket)
    if tenant_slug:
        stmt = stmt.where(ConsoleSupportTicket.tenant_slug == tenant_slug)
    if status_filter:
        stmt = stmt.where(ConsoleSupportTicket.status == status_filter)
    stmt = stmt.order_by(ConsoleSupportTicket.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    open_count = sum(1 for r in rows if r.status == "open")
    in_progress_count = sum(1 for r in rows if r.status == "in_progress")
    return SupportTicketsList(
        items=[SupportTicketRead.model_validate(r) for r in rows],
        open_count=open_count,
        in_progress_count=in_progress_count,
    )


@router.post(
    "/support/tickets",
    response_model=SupportTicketRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_ticket(
    request: Request,
    payload: SupportTicketCreate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> SupportTicketRead:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "support.write")
    if payload.severity not in ("low", "medium", "high", "critical"):
        raise HTTPException(status_code=400, detail="invalid severity")
    ticket = ConsoleSupportTicket(
        tenant_slug=payload.tenant_slug,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        reporter_email=payload.reporter_email,
    )
    db.add(ticket)
    await db.flush()
    return SupportTicketRead.model_validate(ticket)


@router.patch(
    "/support/tickets/{ticket_id}",
    response_model=SupportTicketRead,
)
async def update_support_ticket(
    ticket_id: str,
    payload: SupportTicketUpdate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> SupportTicketRead:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "support.write")
    row = (
        await db.execute(
            select(ConsoleSupportTicket).where(ConsoleSupportTicket.id == ticket_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is not None:
            setattr(row, k, v)
    if row.status in ("resolved", "closed") and row.resolved_at is None:
        row.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return SupportTicketRead.model_validate(row)


# ── Impersonation (It7) ────────────────────────────────────────────


@router.post(
    "/tenants/{slug}/impersonate",
    response_model=ImpersonationSessionRead,
)
async def start_impersonation(
    slug: str,
    request: Request,
    payload: ImpersonationStartRequest,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ImpersonationSessionRead:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "impersonate")
    if not payload.customer_consent:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "customer_consent_required",
                "detail": (
                    "Impersonation requires explicit customer_consent=true. "
                    "Confirm the customer has authorised this session in the ticket."
                ),
            },
        )
    if not payload.reason or len(payload.reason.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Reason required (min 10 chars)",
        )
    session_row = ConsoleImpersonationSession(
        actor_email=user.email,
        tenant_slug=slug,
        target_user_email=payload.target_user_email.lower(),
        reason=payload.reason,
        ticket_id=payload.ticket_id,
        customer_consent=True,
    )
    db.add(session_row)
    await db.flush()
    await audit_action(
        db, actor=user, action=AuditAction.GRANT_ROLE,  # closest enum value
        tenant_slug=slug, result=AuditResult.SUCCESS,
        request_payload={
            "impersonation_start": True,
            "target": payload.target_user_email,
            "ticket_id": payload.ticket_id,
            "reason_preview": payload.reason[:120],
        },
        actor_ip=_ip(request),
    )
    return _impersonation_read(session_row)


@router.post(
    "/impersonation/{session_id}/end",
    response_model=ImpersonationSessionRead,
)
async def end_impersonation(
    session_id: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ImpersonationSessionRead:
    row = (
        await db.execute(
            select(ConsoleImpersonationSession).where(
                ConsoleImpersonationSession.id == session_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.ended_at is None:
        # Cap the explicit close at expires_at so a session that was
        # already past its TTL doesn't get "extended" by a late close
        # — the row's lifetime should not depend on operator promptness.
        from src.core.impersonation_ttl import compute_expires_at

        now = datetime.now(timezone.utc)
        exp = compute_expires_at(row.started_at)
        row.ended_at = min(now, exp) if exp is not None else now
        await db.flush()
    return _impersonation_read(row)


@router.get(
    "/impersonation",
    response_model=List[ImpersonationSessionRead],
)
async def list_impersonation_sessions(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(100, ge=1, le=500),
) -> List[ImpersonationSessionRead]:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    # Everyone with audit.read can see the impersonation log
    console_rbac.assert_permission(my_roles, "audit.read")
    rows = (
        await db.execute(
            select(ConsoleImpersonationSession)
            .order_by(ConsoleImpersonationSession.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_impersonation_read(r) for r in rows]


# ── Compliance / DPO (It6) ─────────────────────────────────────────


async def _get_or_create_compliance(
    db: AsyncSession, tenant_slug: str
) -> ConsoleTenantCompliance:
    row = (
        await db.execute(
            select(ConsoleTenantCompliance).where(
                ConsoleTenantCompliance.tenant_slug == tenant_slug
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = ConsoleTenantCompliance(
        tenant_slug=tenant_slug,
        compliance_flags={},
        subprocessors_approved=[],
    )
    db.add(row)
    await db.flush()
    return row


@router.get(
    "/tenants/{slug}/compliance",
    response_model=ComplianceRead,
)
async def get_tenant_compliance(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ComplianceRead:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "compliance.read")
    tenant_exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant_exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    row = await _get_or_create_compliance(db, slug)
    return ComplianceRead.model_validate(row)


@router.put(
    "/tenants/{slug}/compliance",
    response_model=ComplianceRead,
)
async def update_tenant_compliance(
    slug: str,
    request: Request,
    payload: ComplianceUpdate,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ComplianceRead:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "compliance.write")
    tenant_exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant_exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    row = await _get_or_create_compliance(db, slug)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is not None:
            setattr(row, k, v)
    row.updated_by = user.email
    await db.flush()
    await audit_action(
        db, actor=user, action=AuditAction.UPDATE_TENANT,
        tenant_slug=slug, result=AuditResult.SUCCESS,
        request_payload={"compliance_update": list(changes.keys())},
        actor_ip=_ip(request),
    )
    return ComplianceRead.model_validate(row)


@router.get("/compliance/summary", response_model=ComplianceSummary)
async def compliance_summary(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> ComplianceSummary:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "compliance.read")
    tenants = (await db.execute(select(Tenant))).scalars().all()
    rows: List[ConsoleTenantCompliance] = []
    for t in tenants:
        rows.append(await _get_or_create_compliance(db, t.slug))
    by_residency: dict[str, int] = {}
    signed = pending = expired = 0
    for r in rows:
        by_residency[r.data_residency] = by_residency.get(r.data_residency, 0) + 1
        if r.dpa_status == "signed":
            signed += 1
        elif r.dpa_status == "expired":
            expired += 1
        else:
            pending += 1
    items = [ComplianceRead.model_validate(r) for r in rows]
    return ComplianceSummary(
        total_tenants=len(rows),
        dpa_signed=signed,
        dpa_pending=pending,
        dpa_expired=expired,
        by_residency=by_residency,
        items=items,
    )


@router.get("/tenants/{slug}/dsar")
async def export_dsar(
    slug: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Export audit log entries scoped to one tenant — GDPR DSAR.

    Returns a JSON document the operator can hand back to the
    customer. Heavily audited.
    """
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "audit.export_dsar")
    tenant_exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant_exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit_rows = (
        await db.execute(
            select(InternalConsoleAudit)
            .where(InternalConsoleAudit.tenant_slug == slug)
            .order_by(InternalConsoleAudit.timestamp.desc())
        )
    ).scalars().all()
    compliance = await _get_or_create_compliance(db, slug)
    await audit_action(
        db, actor=user, action=AuditAction.VIEW_AUDIT,
        tenant_slug=slug, result=AuditResult.SUCCESS,
        request_payload={"dsar_export": True, "rows": len(audit_rows)},
        actor_ip=_ip(request),
    )
    return {
        "tenant_slug": slug,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_by": user.email,
        "compliance": ComplianceRead.model_validate(compliance).model_dump(mode="json"),
        "audit_entries": [
            AuditEntryRead.model_validate(r).model_dump(mode="json") for r in audit_rows
        ],
        "audit_entry_count": len(audit_rows),
    }


@router.delete(
    "/role-grants/{user_email}/{role}",
)
async def revoke_role_grant(
    user_email: str,
    role: str,
    request: Request,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "rbac.write")
    try:
        role_enum = ConsoleRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown role")
    revoked = await console_rbac.revoke_role(
        db,
        user_email=user_email,
        role=role_enum,
        revoked_by=user.email,
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="Grant not found")
    await audit_action(
        db,
        actor=user,
        action=AuditAction.REVOKE_ROLE,
        tenant_slug=None,
        result=AuditResult.SUCCESS,
        request_payload={
            "user_email": user_email.lower(),
            "role": role_enum.value,
        },
        actor_ip=_ip(request),
    )
    return {"status": "revoked"}


# ── Telemetry: platform-level ──────────────────────────────────────


@router.get("/dashboard/health", response_model=PlatformHealthResponse)
async def get_platform_health(
    user: User = Depends(require_sky_team),
) -> PlatformHealthResponse:
    try:
        data = infra_provider().platform_health()
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return PlatformHealthResponse(**data.__dict__)


@router.get("/dashboard/activity", response_model=DashboardActivityResponse)
async def get_dashboard_activity(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardActivityResponse:
    slugs = (
        await db.execute(select(Tenant.slug).where(Tenant.is_active == True))  # noqa: E712
    ).scalars().all()
    points = activity_provider().platform_activity_24h(slugs)
    return DashboardActivityResponse(
        points=[p.__dict__ for p in points],
        tenants=list(slugs),
    )


@router.get("/dashboard/cost", response_model=CostBreakdownModel)
async def get_platform_cost(
    user: User = Depends(require_sky_team),
) -> CostBreakdownModel:
    try:
        data = cost_provider().platform_cost()
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return CostBreakdownModel(
        period_start=data.period_start,
        period_end=data.period_end,
        compute_usd=data.compute_usd,
        storage_usd=data.storage_usd,
        network_usd=data.network_usd,
        bedrock_usd=data.bedrock_usd,
        total_usd=data.total_usd,
        daily=[p.__dict__ for p in data.daily],
    )


@router.get("/dashboard/revenue", response_model=RevenueSummaryResponse)
async def get_revenue_summary(
    user: User = Depends(require_sky_team),
) -> RevenueSummaryResponse:
    try:
        data = billing_provider().revenue_summary()
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return RevenueSummaryResponse(**data)


@router.get("/dashboard/alerts", response_model=AlertsResponse)
async def get_alerts(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> AlertsResponse:
    """Return the alerts list filtered to tenants that actually exist."""
    raw = billing_provider().alerts()
    valid_slugs = set(
        (
            await db.execute(select(Tenant.slug))
        ).scalars().all()
    )
    items = [a for a in raw if a.tenant_slug is None or a.tenant_slug in valid_slugs]
    return AlertsResponse(items=[a.__dict__ for a in items])


# ── Telemetry: per-tenant ──────────────────────────────────────────


@router.get(
    "/tenants/{slug}/health",
    response_model=TenantHealthResponse,
)
async def get_tenant_health(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantHealthResponse:
    exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        data = infra_provider().tenant_health(slug)
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return TenantHealthResponse(
        pods=[p.__dict__ for p in data.pods],
        last_deploy_at=data.last_deploy_at,
        last_deploy_sha=data.last_deploy_sha,
        argocd_url=data.argocd_url,
        grafana_url=data.grafana_url,
    )


@router.get(
    "/tenants/{slug}/activity",
    response_model=TenantActivityResponse,
)
async def get_tenant_activity(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantActivityResponse:
    exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    points = activity_provider().tenant_activity_7d(slug)
    total = int(sum(p.value for p in points))
    return TenantActivityResponse(
        points_7d=[p.__dict__ for p in points],
        total_queries_7d=total,
        total_agents_runs_7d=int(total * 0.08),
    )


@router.get(
    "/tenants/{slug}/cost",
    response_model=CostBreakdownModel,
)
async def get_tenant_cost(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> CostBreakdownModel:
    exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        data = cost_provider().tenant_cost(slug)
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return CostBreakdownModel(
        period_start=data.period_start,
        period_end=data.period_end,
        compute_usd=data.compute_usd,
        storage_usd=data.storage_usd,
        network_usd=data.network_usd,
        bedrock_usd=data.bedrock_usd,
        total_usd=data.total_usd,
        daily=[p.__dict__ for p in data.daily],
    )


@router.get(
    "/tenants/{slug}/billing",
    response_model=TenantBillingResponse,
)
async def get_tenant_billing(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> TenantBillingResponse:
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    data = billing_provider().tenant_billing(slug, row.tier)
    return TenantBillingResponse(**data.__dict__)


# ── LLM cost metrics (Langfuse-backed) ─────────────────────────────


def _llm_metrics_to_response(metrics) -> "LlmMetricsResponse":
    """Adapt the service's dataclass to the wire schema.

    Flatten ``by_model`` from a dict-of-dicts into the ``LlmByModelRow``
    list expected by the Console UI so the wire format is stable
    regardless of how the provider chooses to key the breakdown
    internally.
    """
    return LlmMetricsResponse(
        tenant_id=metrics.tenant_id,
        window_days=metrics.window_days,
        from_ts=metrics.from_ts,
        to_ts=metrics.to_ts,
        total_requests=metrics.total_requests,
        total_input_tokens=metrics.total_input_tokens,
        total_output_tokens=metrics.total_output_tokens,
        total_cost_usd=metrics.total_cost_usd,
        total_cost_eur=metrics.total_cost_eur,
        by_model=[
            LlmByModelRow(
                model=model,
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                requests=int(payload.get("requests") or 0),
                cost_usd=float(payload.get("cost_usd") or 0.0),
            )
            for model, payload in (metrics.by_model or {}).items()
        ],
        cache_hit_rate_pct=metrics.cache_hit_rate_pct,
        avg_latency_ms=metrics.avg_latency_ms,
        available=metrics.available,
        unavailable_reason=metrics.unavailable_reason,
    )


@router.get(
    "/tenants/{slug}/llm-metrics",
    response_model=LlmMetricsResponse,
    summary="Per-tenant LLM cost / usage (Langfuse)",
    description=(
        "30-day default window. Reads trace aggregates from Langfuse "
        "and rolls them up by model. Best-effort: returns "
        "``available=false`` when Langfuse is offline / disabled, "
        "never 503s — the Console renders a 'metrics off' pill."
    ),
)
async def get_tenant_llm_metrics(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    days: int = Query(30, ge=1, le=365),
) -> LlmMetricsResponse:
    exists = (
        await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from src.services.llm_cost_metrics import llm_cost_metrics_provider

    # Langfuse trace tags use the tenant slug (matches the
    # ``tenant:<slug>`` convention emitted by the sky-poc-ai callback).
    metrics = llm_cost_metrics_provider().get_tenant_llm_metrics(
        tenant_id=slug, days=days
    )
    return _llm_metrics_to_response(metrics)


@router.get(
    "/platform/llm-metrics",
    response_model=LlmMetricsResponse,
    summary="Platform-wide LLM cost / usage (Langfuse)",
    description=(
        "Sum across every tenant in the Langfuse project. Same "
        "best-effort contract as ``/tenants/{slug}/llm-metrics``."
    ),
)
async def get_platform_llm_metrics(
    user: User = Depends(require_sky_team),
    days: int = Query(30, ge=1, le=365),
) -> LlmMetricsResponse:
    from src.services.llm_cost_metrics import llm_cost_metrics_provider

    metrics = llm_cost_metrics_provider().get_platform_llm_metrics(days=days)
    return _llm_metrics_to_response(metrics)


# ── Global infra + incidents ───────────────────────────────────────


@router.get("/infra", response_model=InfraResponse)
async def get_infrastructure(
    user: User = Depends(require_sky_team),
) -> InfraResponse:
    try:
        nodes = infra_provider().cluster_nodes()
        health = infra_provider().platform_health()
    except TelemetryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return InfraResponse(
        nodes=[n.__dict__ for n in nodes],
        platform_health=PlatformHealthResponse(**health.__dict__),
    )


@router.get("/incidents", response_model=IncidentsResponse)
async def get_incidents(
    user: User = Depends(require_sky_team),
) -> IncidentsResponse:
    items = billing_provider().incidents()
    return IncidentsResponse(items=[i.__dict__ for i in items])


# ── Logs streaming (WebSocket) ─────────────────────────────────────
# Mock implementation that emits one fake log line per second per pod
# until the client disconnects. Real wiring uses ``kubectl logs --follow``
# via the kubernetes-client library.


@router.websocket("/tenants/{slug}/logs/stream")
async def stream_tenant_logs(
    websocket: WebSocket,
    slug: str,
    pod: str = "sky-be",
    token: str = Query(..., description="JWT access token"),
) -> None:
    """Stream pseudo-logs for the chosen tenant pod.

    Sky-team only — when the real ``kubectl logs --follow`` plumbing
    lands behind this, any unauthenticated socket would be a tenant-data
    exfiltration vector. The browser WebSocket API cannot set custom
    headers, so the JWT comes in as ``?token=``; we run the same
    ``verify_token`` + ``is_sky_team_member`` check the HTTP endpoints
    use, then close with 4001/4003 on mismatch (close codes the FE
    can route on).
    """
    import asyncio
    import json as _json
    import random as _rnd

    from src.api.console_auth import is_sky_team_member
    from src.config.database import AsyncSessionLocal
    from src.core.security import verify_token
    from src.repositories.user import UserRepository

    await websocket.accept()

    # 1. Authenticate the socket. Anything off-spec collapses into a
    # short error frame + 4001 close so the FE can reopen with a fresh
    # token without an exception bubbling.
    try:
        payload = verify_token(token, token_type="access")
        user_id = payload.get("sub")
        if not user_id:
            await websocket.send_text(_json.dumps({"error": "unauthenticated"}))
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.send_text(_json.dumps({"error": "unauthenticated"}))
        await websocket.close(code=4001)
        return

    # 2. Load the user + assert they're on the Sky engineering team. The
    # check mirrors ``require_sky_team`` exactly so the WS surface can
    # never grant more than the HTTP one. Non-Sky users get 4003.
    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_id(user_id)
        if user is None or not is_sky_team_member(user):
            await websocket.send_text(_json.dumps({"error": "sky_team_required"}))
            await websocket.close(code=4003)
            return

        # 3. Tenant-existence check on the same session so we don't
        # acquire a second connection from the pool unnecessarily.
        exists = (
            await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
        ).scalar_one_or_none()
    if exists is None:
        await websocket.send_text(_json.dumps({"error": "tenant_not_found"}))
        await websocket.close(code=4004)
        return

    levels = ["INFO", "INFO", "INFO", "INFO", "WARN", "ERROR"]
    components = {
        "sky-be": "uvicorn",
        "sky-fe": "next",
        "sky-ai": "langgraph",
        "sky-ai-worker": "celery",
    }
    comp_label = components.get(pod, pod)
    try:
        i = 0
        while True:
            i += 1
            lvl = _rnd.choice(levels)
            msg = {
                "INFO": "request handled",
                "WARN": "slow query detected",
                "ERROR": "connection reset by peer",
            }[lvl]
            await websocket.send_text(
                _json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "pod": pod,
                        "component": comp_label,
                        "level": lvl,
                        "message": f"{msg} (seq #{i})",
                    }
                )
            )
            await asyncio.sleep(0.6 + _rnd.random() * 0.6)
    except Exception:  # noqa: BLE001 — client disconnect is normal
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# ── Notifications + Comparison + Board Pack (It8) ──────────────────


@router.get("/notifications", response_model=NotificationsResponse)
async def get_notifications(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationsResponse:
    """Aggregate alerts + open tickets + recent failed jobs into a
    single feed the Console bell can render."""
    items: List[Notification] = []

    # 1. Alerts
    alerts_raw = billing_provider().alerts()
    valid_slugs = set(
        (await db.execute(select(Tenant.slug))).scalars().all()
    )
    for a in alerts_raw:
        if a.tenant_slug and a.tenant_slug not in valid_slugs:
            continue
        items.append(
            Notification(
                id=f"alert:{a.title}",
                category="alert",
                severity=a.severity,
                title=a.title,
                detail=a.detail,
                tenant_slug=a.tenant_slug,
                href=(
                    f"/console/tenants/{a.tenant_slug}"
                    if a.tenant_slug
                    else "/console/incidents"
                ),
                timestamp=datetime.fromisoformat(a.fired_at.replace("Z", "+00:00")),
            )
        )

    # 2. Open tickets
    open_tickets = (
        await db.execute(
            select(ConsoleSupportTicket)
            .where(ConsoleSupportTicket.status.in_(["open", "in_progress"]))
            .order_by(ConsoleSupportTicket.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    for t in open_tickets:
        items.append(
            Notification(
                id=f"ticket:{t.id}",
                category="ticket",
                severity=(
                    "critical"
                    if t.severity == "critical"
                    else "warning"
                    if t.severity == "high"
                    else "info"
                ),
                title=f"Support · {t.title}",
                detail=f"{t.tenant_slug} · {t.severity}",
                tenant_slug=t.tenant_slug,
                href=f"/console/support",
                timestamp=t.created_at,
            )
        )

    # 3. Recent failed jobs
    failed_jobs = (
        await db.execute(
            select(ProvisioningJob)
            .where(ProvisioningJob.status == "failed")
            .order_by(ProvisioningJob.started_at.desc())
            .limit(10)
        )
    ).scalars().all()
    for j in failed_jobs:
        items.append(
            Notification(
                id=f"job:{j.id}",
                category="job",
                severity="warning",
                title=f"Job failed · {j.job_type}",
                detail=f"{j.tenant_slug} · {j.actor_email}",
                tenant_slug=j.tenant_slug,
                href=f"/console/jobs",
                timestamp=j.started_at,
            )
        )

    items.sort(key=lambda x: x.timestamp, reverse=True)
    return NotificationsResponse(items=items, unread_count=len(items))


@router.get("/compare", response_model=TenantCompareResponse)
async def compare_tenants(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    slugs: str = Query(..., description="comma-separated slugs"),
) -> TenantCompareResponse:
    slug_list = [s.strip() for s in slugs.split(",") if s.strip()]
    if not slug_list:
        raise HTTPException(status_code=400, detail="No slugs supplied")
    if len(slug_list) > 5:
        raise HTTPException(status_code=400, detail="Max 5 tenants per compare")

    items: List[TenantCompareEntry] = []
    for slug in slug_list:
        t = (
            await db.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if t is None:
            continue
        csm_resp = await csm_service.build_csm_response(db, slug)
        preset = pricing_tiers.get_tier(t.tier)
        items.append(
            TenantCompareEntry(
                slug=t.slug,
                display_name=t.display_name,
                tier=t.tier,
                is_active=t.is_active,
                capacity_used=t.capacity_used or {},
                capacity_limits=t.capacity_limits or {},
                health_score=csm_resp.health_score if csm_resp else 0,
                health_breakdown=csm_resp.health_breakdown if csm_resp else {},
                queries_7d=int(
                    sum(p.value for p in activity_provider().tenant_activity_7d(slug))
                ),
                monthly_eur=(
                    preset.headline_price_eur / 12.0
                    if preset and preset.headline_price_eur
                    else 0.0
                ),
            )
        )
    return TenantCompareResponse(items=items)


@router.get("/board-pack", response_model=BoardPackResponse)
async def get_board_pack(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> BoardPackResponse:
    """Single-shot CEO board snapshot. JSON the UI can render or
    download as PDF. v2 wires a server-side weasyprint render."""
    my_roles = await console_rbac.load_active_roles(db, user.email)
    console_rbac.assert_permission(my_roles, "revenue.read")

    summary = await console_service.dashboard_summary(db)
    cost = cost_provider().platform_cost()
    revenue = billing_provider().revenue_summary()
    tenants = (await db.execute(select(Tenant))).scalars().all()

    # Customers at risk
    at_risk: list[dict] = []
    for t in tenants:
        csm_resp = await csm_service.build_csm_response(db, t.slug)
        if csm_resp and csm_resp.health_score < 70:
            at_risk.append({
                "slug": t.slug,
                "display_name": t.display_name,
                "tier": t.tier,
                "health_score": csm_resp.health_score,
            })

    renewals = await csm_service.upcoming_renewals(db, days_ahead=90)

    incidents = billing_provider().incidents()

    return BoardPackResponse(
        generated_at=datetime.now(timezone.utc),
        generated_by=user.email,
        metrics={
            "total_tenants": float(summary.total_tenants),
            "active_tenants": float(summary.active_tenants),
            "suspended_tenants": float(summary.suspended_tenants),
            "mrr_eur": revenue["mrr_eur"],
            "arr_run_rate_eur": revenue["mrr_eur"] * 12,
            "spend_mtd_usd": cost.total_usd,
            "projected_eom_usd": revenue["projection_eom_usd"],
            "gross_margin_pct": revenue["gross_margin_pct"],
        },
        tenants_by_tier=summary.tenants_by_tier,
        customers_at_risk=at_risk,
        renewals_next_90d=[
            {
                "slug": r.tenant_slug,
                "display_name": r.display_name,
                "tier": r.tier,
                "days_until": r.days_until,
                "monthly_eur": r.monthly_amount_eur,
            }
            for r in renewals
        ],
        cost_breakdown={
            "compute": cost.compute_usd,
            "bedrock": cost.bedrock_usd,
            "storage": cost.storage_usd,
            "network": cost.network_usd,
            "total": cost.total_usd,
        },
        revenue_summary=revenue,
        incidents_recent=[
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "started_at": i.started_at,
                "resolved_at": i.resolved_at,
                "affected_tenants": i.affected_tenants,
            }
            for i in incidents
        ],
    )


# ── Pricing — per-tenant usage (Fase 1) ────────────────────────────


@router.get(
    "/tenants/{slug}/usage",
    summary="Per-tenant pricing limits + live usage breakdown",
)
async def get_tenant_usage(
    slug: str,
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Console view: ceilings, current counters, and percent per resource.

    Used by the Pricing tab in the Console to render the "agents
    8/10" style indicators and the 80/95/100 progress bars. The
    response is intentionally flat JSON (not a Pydantic model) so the
    Fase 2 FE iteration can ship without a schema round-trip — the
    shape is documented inline below.
    """
    tenant_q = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = tenant_q.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    row = await pricing_service.get_limits(db, tenant.id)
    percent = await pricing_service.usage_percent(db, tenant.id)
    return {
        "tenant_slug": slug,
        "tenant_id": str(tenant.id),
        "tier": row.tier,
        "limits": {
            "max_agents": row.max_agents,
            "max_users": row.max_users,
            "max_storage_gb": row.max_storage_gb,
            "max_queries_per_month": row.max_queries_per_month,
        },
        "current": {
            "agents": row.current_agents,
            "users": row.current_users,
            "storage_bytes": row.current_storage_bytes,
            "queries_this_month": row.current_queries_this_month,
        },
        "percent": percent,
        "queries_period_start": row.queries_period_start,
        "last_threshold_alerted": row.last_threshold_alerted or {},
        "updated_at": row.updated_at,
    }
