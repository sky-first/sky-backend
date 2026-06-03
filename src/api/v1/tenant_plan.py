"""Tenant plan tier endpoints.

GET — open to any authenticated user (the topbar usage card and the
profile dropdown both render the tier label).

PUT — owner-only. Plan tier is a contractual / billing concern, so
even Admins are kept out by default; flip to admin_or_above only if
product later decides admins should self-serve plan changes too.

When Stripe wiring lands, the writer here is replaced (or supplemented)
by the webhook handler that flips the tier when a contract changes.

The customer-facing ``/usage`` + ``/usage/alert`` pair (Pricing Fase 2)
also lives here because both endpoints share the same router prefix
("/tenant-plan") and the same auth posture — any authenticated user
can read their own tenant's usage.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.internal_console import InternalConsoleAudit
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.tenant_plan import (
    TenantPlanResponse,
    TenantPlanUpdate,
    TenantUsageResponse,
    UsageAlertRequest,
    UsageAlertResponse,
    UsagePercent,
)
from src.services import pricing_service
from src.services.tenant_plan_service import TenantPlanService

router = APIRouter()


def _coerce_unlimited(value: float, ceiling: int | None) -> float | None:
    """0.0 when ceiling is NULL → None — the FE renders that as "—".

    The pricing_service.usage_percent helper folds unlimited resources
    into 0.0 so the Console "8/10 (0%)" math doesn't blow up; the
    customer-facing API is stricter — None is the only honest answer
    when the contract is uncapped.
    """
    return None if ceiling is None else round(value, 4)


def _row_to_response(row) -> TenantPlanResponse:
    return TenantPlanResponse(
        plan_tier=row.plan_tier,
        updated_at=row.updated_at,
        updated_by_user_id=str(row.updated_by_user_id) if row.updated_by_user_id else None,
    )


@router.get(
    "",
    response_model=TenantPlanResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get tenant plan tier",
    description=(
        "Returns the contracted plan tier for this tenant. Open to any "
        "authenticated user — the topbar usage card needs it to render "
        "the right label and to decide whether to surface upgrade copy."
    ),
)
async def get_tenant_plan(
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: AsyncSession = Depends(get_db_session),
) -> TenantPlanResponse:
    row = await TenantPlanService(db).get()
    return _row_to_response(row)


@router.put(
    "",
    response_model=TenantPlanResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Update tenant plan tier (owner only)",
    description=(
        "Sets the contracted plan tier. Owner-only — billing is a "
        "contractual concern, not an operational one. Once Stripe is "
        "wired this endpoint becomes a manual override; the canonical "
        "source of truth becomes the webhook."
    ),
)
async def update_tenant_plan(
    patch: TenantPlanUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TenantPlanResponse:
    if current_user.role not in ("super_admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the tenant SuperAdmin can change the plan tier.",
        )
    row = await TenantPlanService(db).set_tier(
        plan_tier=patch.plan_tier,
        updated_by_user_id=str(current_user.id),
    )
    await db.commit()
    return _row_to_response(row)


# ─── Pricing Fase 2 — customer-facing usage ────────────────────────


@router.get(
    "/usage",
    response_model=TenantUsageResponse,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Live usage snapshot for the caller's tenant",
    description=(
        "Returns ceilings + current counters for the caller's tenant, "
        "scoped to whatever the tenant resolver middleware attached to "
        "the request. Drives the topbar `<PlanUsagePill />`, the agent "
        "create modal slot hint, and the 80%/95% in-app toasts. "
        "Unlimited resources (Enterprise) report null for both the "
        "ceiling and the percent so the FE renders '—'."
    ),
)
async def get_my_tenant_usage(
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: AsyncSession = Depends(get_db_session),
) -> TenantUsageResponse:
    row = await pricing_service.get_limits(db)
    percent = await pricing_service.usage_percent(db)

    return TenantUsageResponse(
        tier=row.tier,
        max_agents=row.max_agents,
        current_agents=row.current_agents,
        max_users=row.max_users,
        current_users=row.current_users,
        max_storage_gb=row.max_storage_gb,
        current_storage_bytes=row.current_storage_bytes,
        max_queries_per_month=row.max_queries_per_month,
        current_queries_this_month=row.current_queries_this_month,
        usage_percent=UsagePercent(
            agents=_coerce_unlimited(percent["agents"], row.max_agents),
            users=_coerce_unlimited(percent["users"], row.max_users),
            storage=_coerce_unlimited(percent["storage"], row.max_storage_gb),
            queries=_coerce_unlimited(
                percent["queries"], row.max_queries_per_month
            ),
        ),
        queries_period_start=row.queries_period_start,
        updated_at=row.updated_at,
    )


@router.post(
    "/usage/alert",
    response_model=UsageAlertResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={401: {"model": ErrorResponse}},
    summary="Log a tier-threshold alert intent (Fase 2 stub)",
    description=(
        "FE calls this when a user crosses a 80/95/100 threshold in "
        "their session. We record the intent in the Console audit log "
        "so the Fase 4 email + Stripe webhook worker can replay it. "
        "Idempotency is best-effort: the pricing_service bumps already "
        "track which thresholds fired per period; this endpoint just "
        "captures the FE-side acknowledgement so we can audit drift "
        "between server- and client-detected crossings."
    ),
)
async def log_usage_alert(
    payload: UsageAlertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UsageAlertResponse:
    # Audit-only for Fase 2 — the real email + Stripe paywall lands
    # in Fase 4 once we have a billing identity to bill against.
    row = await pricing_service.get_limits(db)

    audit = InternalConsoleAudit(
        actor_email=current_user.email or "unknown@unknown",
        action="update_capacity",  # reused per pricing_service comment
        tenant_slug=None,
        result="success",
        result_details={
            "intent": "tier_threshold_crossed_alert_intent",
            "tenant_id": str(row.tenant_id),
            "tier": row.tier,
            "resource": payload.resource,
            "threshold": payload.threshold,
            "current_percent": round(payload.current_percent, 2),
            "user_id": str(current_user.id),
            "user_role": current_user.role,
        },
    )
    db.add(audit)
    await db.flush()
    audit_id = str(audit.id) if getattr(audit, "id", None) else None
    await db.commit()
    return UsageAlertResponse(accepted=True, audit_id=audit_id)
