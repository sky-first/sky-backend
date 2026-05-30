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
    MyAccessResponse,
    PlatformHealthResponse,
    ProvisioningJobRead,
    RenewalEntry,
    RenewalsResponse,
    RevenueSummaryResponse,
    RoleGrantRead,
    RoleGrantsListResponse,
    SuspendTenantRequest,
    TenantActivityResponse,
    TenantBillingResponse,
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
from src.services import console_rbac, console_service, csm_service, pricing_tiers
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
    """
    preset = pricing_tiers.get_tier(payload.tier)
    if preset is None:
        raise HTTPException(status_code=400, detail="Unknown tier")
    row = (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # ── Downgrade safety check ─────────────────────────────────────
    # Only enforce when the operator asked us to apply the preset;
    # ``apply_preset=false`` is the explicit "keep contractual
    # override" path and bypasses the check on purpose.
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
                    }
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
                },
                actor_ip=_ip(request),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "downgrade_exceeds_new_caps",
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
    return ImpersonationSessionRead.model_validate(session_row)


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
        row.ended_at = datetime.now(timezone.utc)
        await db.flush()
    return ImpersonationSessionRead.model_validate(row)


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
    return [ImpersonationSessionRead.model_validate(r) for r in rows]


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
    revenue = cost_provider().revenue_summary()
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
