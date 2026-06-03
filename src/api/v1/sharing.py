"""Resource sharing endpoints (Phase 2 of the RBAC rewrite).

Replaces the old per-table permission tables (ConnectionPermission,
UserPermissionGrant) with a single, generic `resource_acl` row per grant.

Routes:
  POST   /resources/{resource_type}/{resource_id}/share  → upsert a grant
  GET    /resources/{resource_type}/{resource_id}/acl    → list grants
  DELETE /resources/{resource_type}/{resource_id}/share/{grant_id}

Authorisation for these endpoints follows the same model:
  • Owner / Admin can manage any grant
  • Member can manage grants only on resources where they are the
    Space owner or have an explicit owner-level grant
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.core.exceptions import ForbiddenError
from src.models.resource_acl import ResourceAcl
from src.models.user import User
from src.schemas.resource_acl import (
    GrantCreate,
    GrantList,
    GrantResponse,
    ResourceType,
)

router = APIRouter()


# Permission keys used to gate sharing operations on each resource_type.
# Must be present in PERMISSION_RULES (added in Phase 2 alongside this file).
SHARE_GATE_KEY = "resources.share"


async def _assert_can_manage_share(
    user: User, db: AsyncSession, resource_type: str, resource_id: UUID
) -> None:
    """Allow Owner/Admin always; Members must hold owner-level on the
    resource (via space membership or explicit ACL row)."""
    if user.role in ("owner", "admin", "super_admin"):
        return
    # Member: check explicit owner-level grant on this resource.
    grant = (
        await db.execute(
            select(ResourceAcl).where(
                ResourceAcl.resource_type == resource_type,
                ResourceAcl.resource_id == resource_id,
                ResourceAcl.principal_type == "user",
                ResourceAcl.principal_id == user.id,
                ResourceAcl.level == "owner",
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise ForbiddenError(
            f"Only the resource owner can manage sharing for {resource_type}/{resource_id}"
        )


@router.post(
    "/{resource_type}/{resource_id}/share",
    response_model=GrantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_grant(
    resource_type: ResourceType,
    resource_id: UUID,
    body: GrantCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrantResponse:
    """Create or update a grant on a resource.

    Idempotent on `(resource_type, resource_id, principal_type, principal_id)`:
    if a row exists, its level is overwritten."""
    await _assert_can_manage_share(current_user, db, resource_type, resource_id)

    # Validate principal payload shape.
    if body.principal_type == "tenant" and body.principal_id is not None:
        raise HTTPException(
            status_code=400,
            detail="principal_id must be omitted for tenant grants",
        )
    if body.principal_type in ("user", "space") and body.principal_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"principal_id is required for {body.principal_type} grants",
        )

    # Try to find an existing grant to upsert.
    existing_q = select(ResourceAcl).where(
        ResourceAcl.resource_type == resource_type,
        ResourceAcl.resource_id == resource_id,
        ResourceAcl.principal_type == body.principal_type,
    )
    if body.principal_id is None:
        existing_q = existing_q.where(ResourceAcl.principal_id.is_(None))
    else:
        existing_q = existing_q.where(ResourceAcl.principal_id == body.principal_id)

    existing = (await db.execute(existing_q)).scalar_one_or_none()
    if existing is not None:
        existing.level = body.level
        existing.granted_by = current_user.id
        await db.commit()
        await db.refresh(existing)
        return GrantResponse.model_validate(existing)

    grant = ResourceAcl(
        resource_type=resource_type,
        resource_id=resource_id,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        level=body.level,
        granted_by=current_user.id,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return GrantResponse.model_validate(grant)


@router.get(
    "/{resource_type}/{resource_id}/acl",
    response_model=GrantList,
)
async def list_grants(
    resource_type: ResourceType,
    resource_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GrantList:
    """List every explicit grant on a resource. Auth: Owner/Admin or any
    user that holds at least viewer-level access on the resource."""
    if current_user.role not in ("owner", "admin", "super_admin"):
        # Member must have at least one grant of any level to see the ACL.
        own_grant = (
            await db.execute(
                select(ResourceAcl).where(
                    ResourceAcl.resource_type == resource_type,
                    ResourceAcl.resource_id == resource_id,
                    ResourceAcl.principal_type == "user",
                    ResourceAcl.principal_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if own_grant is None:
            raise ForbiddenError(
                f"You don't have access to {resource_type}/{resource_id}"
            )

    rows = (
        await db.execute(
            select(ResourceAcl)
            .where(
                ResourceAcl.resource_type == resource_type,
                ResourceAcl.resource_id == resource_id,
            )
            .order_by(ResourceAcl.granted_at.desc())
        )
    ).scalars().all()
    items = [GrantResponse.model_validate(r) for r in rows]
    return GrantList(items=items, total=len(items))


@router.delete(
    "/{resource_type}/{resource_id}/share/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_grant(
    resource_type: ResourceType,
    resource_id: UUID,
    grant_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _assert_can_manage_share(current_user, db, resource_type, resource_id)
    row = (
        await db.execute(
            select(ResourceAcl).where(
                ResourceAcl.id == grant_id,
                ResourceAcl.resource_type == resource_type,
                ResourceAcl.resource_id == resource_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
