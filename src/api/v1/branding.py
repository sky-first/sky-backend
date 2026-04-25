"""Tenant-wide branding endpoints.

GET is open to every authenticated user — they need the config on app
boot to render with the right primary color / logo / font.
PUT is owner-only.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.schemas.branding import BrandingConfig, BrandingUpdate
from src.schemas.common import ErrorResponse
from src.services.branding_service import BrandingService

router = APIRouter()


@router.get(
    "",
    response_model=BrandingConfig,
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="Get tenant branding",
    description=(
        "Tenant-wide branding (logo, primary color, font, radius). Read by "
        "every authenticated user on app boot to render the right theme."
    ),
)
async def get_branding(
    current_user: User = Depends(get_current_user),  # noqa: ARG001 — auth gate only
    db: AsyncSession = Depends(get_db_session),
) -> BrandingConfig:
    return await BrandingService(db).get()


@router.put(
    "",
    response_model=BrandingConfig,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Update tenant branding (owner only)",
    description=(
        "Patches one or more fields on the platform branding. Only the "
        "tenant Owner can call this endpoint — Admins and Members get 403. "
        "All connected users see the new branding on next refresh."
    ),
)
async def update_branding(
    patch: BrandingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> BrandingConfig:
    # Branding is a tenant-wide visual choice — admins might be a Sky
    # Labs operator (impersonating, auditing) so we deliberately keep
    # this Owner-exclusive rather than admin-or-owner.
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the tenant owner can change branding.",
        )
    return await BrandingService(db).update(current_user, patch)
