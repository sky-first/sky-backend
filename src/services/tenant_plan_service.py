"""TenantPlanService — read/write the singleton tenant_plan row.

The table is seeded by the migration to ``(id=1, plan_tier='enterprise')``
so reads should always find a row. The service still defends against an
empty table (e.g. fresh dev DB without the seed) by falling back to
'enterprise' on read and creating the row lazily on write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant_plan import TenantPlan

logger = logging.getLogger(__name__)

_DEFAULT_TIER = "enterprise"


class TenantPlanService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self) -> TenantPlan:
        """Return the singleton row, creating it lazily if absent.

        A missing row only happens on a fresh DB whose migration hasn't
        run the seed INSERT yet (or in tests using create_all). We
        materialize it with the default tier so callers downstream
        always have something to render.
        """
        row = (
            await self.db.execute(select(TenantPlan).where(TenantPlan.id == 1))
        ).scalar_one_or_none()
        if row is not None:
            return row

        row = TenantPlan(id=1, plan_tier=_DEFAULT_TIER)
        self.db.add(row)
        await self.db.flush()
        logger.info("tenant_plan: lazily created singleton row with tier=%s", _DEFAULT_TIER)
        return row

    async def set_tier(self, *, plan_tier: str, updated_by_user_id: Optional[str]) -> TenantPlan:
        """Owner-driven update. Caller is expected to have already
        authorised — this service only handles persistence.
        """
        row = await self.get()
        row.plan_tier = plan_tier
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info(
            "tenant_plan: tier set to %s by user=%s",
            plan_tier,
            updated_by_user_id,
        )
        return row
