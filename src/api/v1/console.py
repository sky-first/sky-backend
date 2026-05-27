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
from src.models.user import User
from src.schemas.internal_console import (
    AlertsResponse,
    AuditEntryRead,
    ChangeTierRequest,
    ConsoleMeResponse,
    ConsoleTenantDetail,
    ConsoleTenantList,
    CostBreakdownModel,
    CreateTenantRequest,
    CSMNotesRead,
    CSMNotesUpdate,
    DashboardActivityResponse,
    DashboardSummary,
    DestroyTenantRequest,
    IncidentsResponse,
    InfraResponse,
    PlatformHealthResponse,
    ProvisioningJobRead,
    RenewalEntry,
    RenewalsResponse,
    RevenueSummaryResponse,
    SuspendTenantRequest,
    TenantActivityResponse,
    TenantBillingResponse,
    TenantHealthResponse,
    TierPresetResponse,
    UpdateCapacityLimitsRequest,
    UpdateTenantRequest,
)
from src.services import console_service, csm_service, pricing_tiers
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


@router.get("/jobs", response_model=List[ProvisioningJobRead])
async def list_jobs(
    user: User = Depends(require_sky_team),
    db: AsyncSession = Depends(get_db_session),
    tenant_slug: Optional[str] = Query(None, max_length=50),
    limit: int = Query(100, ge=1, le=500),
) -> List[ProvisioningJobRead]:
    return await console_service.list_jobs(db, tenant_slug=tenant_slug, limit=limit)


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
    preset = pricing_tiers.get_tier(payload.tier)
    if preset is None:
        raise HTTPException(status_code=400, detail="Unknown tier")
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    old_tier = row.tier
    row.tier = preset.slug
    row.rate_limit_rpm = preset.rate_limit_rpm
    row.rate_limit_tpm = preset.rate_limit_tpm
    if payload.apply_preset:
        row.capacity_limits = dict(preset.capacity_limits)
    await db.flush()

    from src.api.middleware.tenant_resolver import clear_tenant_cache

    clear_tenant_cache()

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
        data = cost_provider().revenue_summary()
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
) -> None:
    import asyncio
    import json as _json
    import random as _rnd

    await websocket.accept()
    # Lightweight check: refuse if slug isn't an active tenant. We can't
    # use the dep here (WS doesn't go through the same DI), so do a
    # one-shot lookup using AsyncSessionLocal.
    from src.config.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        exists = (
            await db.execute(select(Tenant.slug).where(Tenant.slug == slug))
        ).scalar_one_or_none()
    if exists is None:
        await websocket.send_text(_json.dumps({"error": "tenant_not_found"}))
        await websocket.close()
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
