"""Owner-only delegations for per-user permission grants.

The first delegable permission is ``knowledge.certify`` (Phase 3 of the
Knowledge refactor). Owner can grant it to specific admins and revoke
at any time. Revocation is soft (``revoked_at`` set) so we keep the
forensic trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from src.models.user import User
from src.models.user_permission_grant import (
    GRANTABLE_PERMISSIONS,
    UserPermissionGrant,
)


def _is_owner(user: User) -> bool:
    return (user.role or "").lower() == "owner"


class PermissionGrantService:
    """Live grant management — Owner-only writes, anyone can read their own."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def grant(
        self, *, granter: User, target_user_id: UUID, permission: str
    ) -> UserPermissionGrant:
        if not _is_owner(granter):
            raise ForbiddenError("only the tenant Owner can grant delegable permissions")
        if permission not in GRANTABLE_PERMISSIONS:
            raise ValidationError(f"permission '{permission}' is not delegable")

        # Idempotent — if a live grant already exists, return it.
        live = await self._get_live(target_user_id, permission)
        if live is not None:
            return live

        grant = UserPermissionGrant(
            user_id=target_user_id,
            permission=permission,
            granted_by_user_id=granter.id,
        )
        self.db.add(grant)
        await self.db.flush()
        await self.db.refresh(grant)
        return grant

    async def revoke(
        self, *, revoker: User, target_user_id: UUID, permission: str
    ) -> None:
        if not _is_owner(revoker):
            raise ForbiddenError("only the tenant Owner can revoke delegable permissions")

        live = await self._get_live(target_user_id, permission)
        if live is None:
            raise NotFoundError("grant not found or already revoked")
        live.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def list_live_for_user(self, user_id: UUID) -> List[UserPermissionGrant]:
        rows = await self.db.execute(
            select(UserPermissionGrant)
            .where(
                UserPermissionGrant.user_id == user_id,
                UserPermissionGrant.revoked_at.is_(None),
            )
            .order_by(UserPermissionGrant.granted_at.desc())
        )
        return list(rows.scalars().all())

    async def _get_live(
        self, user_id: UUID, permission: str
    ) -> UserPermissionGrant | None:
        row = await self.db.execute(
            select(UserPermissionGrant).where(
                UserPermissionGrant.user_id == user_id,
                UserPermissionGrant.permission == permission,
                UserPermissionGrant.revoked_at.is_(None),
            )
        )
        return row.scalar_one_or_none()
