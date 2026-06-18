"""Per-user permission grant endpoints — Owner-only writes.

POST   /api/v1/users/{id}/permission-grants     — Owner grants a delegable permission
DELETE /api/v1/users/{id}/permission-grants/{permission}  — Owner revokes
GET    /api/v1/users/{id}/permission-grants     — list live grants

Knowledge refactor Phase 3.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.services.permission_grant_service import PermissionGrantService

router = APIRouter()


class GrantRequest(BaseModel):
    permission: str


class GrantResponse(BaseModel):
    user_id: UUID
    permission: str
    granted_by_user_id: Optional[UUID]
    granted_at: str


def _to_response(grant) -> GrantResponse:
    return GrantResponse(
        user_id=grant.user_id,
        permission=grant.permission,
        granted_by_user_id=grant.granted_by_user_id,
        granted_at=grant.granted_at.isoformat() if grant.granted_at else "",
    )


@router.post(
    "/{target_user_id}/permission-grants",
    response_model=GrantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_permission(
    target_user_id: UUID,
    body: GrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = PermissionGrantService(db)
    grant = await service.grant(
        granter=current_user, target_user_id=target_user_id, permission=body.permission
    )
    await db.commit()
    return _to_response(grant)


@router.delete(
    "/{target_user_id}/permission-grants/{permission}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_permission(
    target_user_id: UUID,
    permission: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = PermissionGrantService(db)
    await service.revoke(
        revoker=current_user, target_user_id=target_user_id, permission=permission
    )
    await db.commit()


@router.get(
    "/{target_user_id}/permission-grants", response_model=List[GrantResponse]
)
async def list_permission_grants(
    target_user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    # Anyone can read someone's live grants — they're not secret, the
    # information is needed to render UIs that surface "this admin can
    # certify".
    service = PermissionGrantService(db)
    grants = await service.list_live_for_user(target_user_id)
    return [_to_response(g) for g in grants]
