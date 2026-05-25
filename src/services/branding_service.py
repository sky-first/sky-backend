"""Tenant-wide branding service.

Reads and writes the single-row ``platform_branding`` table. Reads are
open to any authenticated user; writes require the tenant Owner role.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.platform_branding import PlatformBranding
from src.models.user import User
from src.schemas.branding import BrandingConfig, BrandingUpdate

logger = logging.getLogger(__name__)

_SINGLETON_ID = 1


class BrandingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> BrandingConfig:
        """Return the active branding config — falling back to defaults
        when no row has been written yet (fresh tenant boot).
        """
        row = await self._get_row()
        if row is None:
            return BrandingConfig()
        return BrandingConfig(
            primary_color=row.primary_color,
            radius=row.radius,
            font_family=row.font_family,
            logo_url=row.logo_url,
            company_name=row.company_name,
            updated_at=row.updated_at,
        )

    async def update(self, current_user: User, patch: BrandingUpdate) -> BrandingConfig:
        """Owner-only write. Patches non-None fields onto the singleton row.

        We let the route enforce the Owner role check via RBAC so this
        method stays pure — it just refuses if no user is provided.
        """
        if current_user is None:  # pragma: no cover  (defensive)
            raise PermissionError("authenticated user required to update branding")

        row = await self._get_row()
        if row is None:
            row = PlatformBranding(id=_SINGLETON_ID)
            self.db.add(row)

        if patch.primary_color is not None:
            row.primary_color = patch.primary_color
        if patch.radius is not None:
            row.radius = patch.radius
        if patch.font_family is not None:
            row.font_family = patch.font_family
        if patch.logo_url is not None:
            row.logo_url = patch.logo_url
        if patch.company_name is not None:
            row.company_name = patch.company_name
        row.updated_by_user_id = current_user.id

        await self.db.flush()
        await self.db.refresh(row)
        return BrandingConfig(
            primary_color=row.primary_color,
            radius=row.radius,
            font_family=row.font_family,
            logo_url=row.logo_url,
            company_name=row.company_name,
            updated_at=row.updated_at,
        )

    async def _get_row(self) -> Optional[PlatformBranding]:
        result = await self.db.execute(
            select(PlatformBranding).where(PlatformBranding.id == _SINGLETON_ID)
        )
        return result.scalar_one_or_none()
