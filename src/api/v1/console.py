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

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.console_auth import (
    audit_action,
    require_sky_team,
    role_for,
)
from src.api.deps import get_db_session
from src.models.internal_console import AuditAction, AuditResult
from src.models.user import User
from src.schemas.internal_console import (
    AuditEntryRead,
    ConsoleMeResponse,
    ConsoleTenantDetail,
    ConsoleTenantList,
    CreateTenantRequest,
    DashboardSummary,
    DestroyTenantRequest,
    ProvisioningJobRead,
    SuspendTenantRequest,
    UpdateTenantRequest,
)
from src.services import console_service

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
