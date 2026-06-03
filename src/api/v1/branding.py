"""Tenant-wide branding endpoints.

GET is OPEN (no auth) so the unauthenticated /login page can show
the customer's logo + company name before the user signs in.
PUT is owner-only.
"""

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.schemas.branding import BrandingConfig, BrandingUpdate
from src.schemas.common import ErrorResponse
from src.services.branding_service import BrandingService

router = APIRouter()


class PublicBrandingConfig(BaseModel):
    """Subset of ``BrandingConfig`` safe to expose without auth.

    Only the bits the /login page needs to render the company's
    identity: ``logo_url`` + ``company_name``. We deliberately do NOT
    surface the operator-controlled visuals (primary_color, radius,
    font_family) — those should not leak before authentication so an
    attacker can't fingerprint a tenant's plan via the visual config.
    """

    logo_url: str | None = None
    company_name: str = "SkyFirstLabs"


@router.get(
    "/public",
    response_model=PublicBrandingConfig,
    status_code=status.HTTP_200_OK,
    summary="Get tenant public branding (no auth)",
    description=(
        "Returns just the logo URL + company name for the currently-"
        "resolved tenant. Used by /login (pre-auth) to render the "
        "customer's identity before they sign in. Falls back to the "
        "SkyFirst default when no tenant is resolved."
    ),
)
async def get_public_branding(
    db: AsyncSession = Depends(get_db_session),
) -> PublicBrandingConfig:
    full = await BrandingService(db).get()
    return PublicBrandingConfig(
        logo_url=full.logo_url,
        company_name=full.company_name,
    )


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
    # this SuperAdmin-exclusive rather than admin-or-above. ``owner`` is
    # accepted for back-compat during the 2026-06-03 role rename.
    if current_user.role not in ("super_admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the tenant SuperAdmin can change branding.",
        )
    return await BrandingService(db).update(current_user, patch)
