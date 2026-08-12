"""Privacy endpoints — DSAR export and erasure (GDPR Art. 15 + 17)."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import BadRequestError, ForbiddenError
from src.core.permissions import is_tenant_admin
from src.models.user import User
from src.services.dsar_service import DSARService

router = APIRouter()


class DSARExportRequest(BaseModel):
    user_email: EmailStr


class DSARDeleteRequest(BaseModel):
    user_email: EmailStr
    confirm: bool = False


class SelfDeleteRequest(BaseModel):
    confirm: bool = False


@router.post(
    "/dsar/export",
    status_code=status.HTTP_200_OK,
    summary="Export user data (GDPR Art. 15)",
    description="Aggregate all data about a user. Admin only.",
)
async def dsar_export(
    request: DSARExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Export all data for a subject (GDPR right of access)."""
    if not is_tenant_admin(current_user):
        raise ForbiddenError("DSAR export requires admin role")

    dsar = DSARService(db)
    return await dsar.export_user_data(request.user_email)


@router.post(
    "/dsar/delete",
    status_code=status.HTTP_200_OK,
    summary="Erase user data (GDPR Art. 17)",
    description="Soft-delete user and anonymize mentions. Owner only.",
)
async def dsar_delete(
    request: DSARDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Erase a user's data (GDPR right to erasure)."""
    # Only tenant-level admins (super_admin or admin) may erase users.
    if not is_tenant_admin(current_user):
        raise ForbiddenError("DSAR erasure requires admin role")

    if not request.confirm:
        raise ForbiddenError("Erasure requires confirm=true")

    dsar = DSARService(db)
    return await dsar.erase_user(request.user_email)


@router.post(
    "/account/delete",
    status_code=status.HTTP_200_OK,
    summary="Delete my own account (GDPR Art. 17)",
    description=(
        "Self-service account deletion: the authenticated user erases their own "
        "account and data — no admin, no support ticket. Required by App Store "
        "review guideline 5.1.1(v) for any app that offers account creation."
    ),
)
async def delete_my_account(
    request: SelfDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Erase the caller's own account (soft-delete + anonymize mentions)."""
    if not request.confirm:
        raise BadRequestError("Account deletion requires confirm=true")

    dsar = DSARService(db)
    return await dsar.erase_user(current_user.email)
