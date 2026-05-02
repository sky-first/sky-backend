"""Tenant plan tier endpoints.

GET — open to any authenticated user (the topbar usage card and the
profile dropdown both render the tier label).

PUT — owner-only. Plan tier is a contractual / billing concern, so
even Admins are kept out by default; flip to admin_or_above only if
product later decides admins should self-serve plan changes too.

When Stripe wiring lands, the writer here is replaced (or supplemented)
by the webhook handler that flips the tier when a contract changes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.tenant_plan import TenantPlanResponse, TenantPlanUpdate
from src.services.tenant_plan_service import TenantPlanService

router = APIRouter()


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
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the tenant owner can change the plan tier.",
        )
    row = await TenantPlanService(db).set_tier(
        plan_tier=patch.plan_tier,
        updated_by_user_id=str(current_user.id),
    )
    await db.commit()
    return _row_to_response(row)
