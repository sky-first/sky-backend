"""Device repository — the push registry's data access (BE-06)."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete as sa_delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import Device
from src.schemas.device import DeviceRegister


class DeviceRepository:
    """Repository for Device."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert(
        self, user_id: UUID, payload: DeviceRegister, tenant_id: Optional[UUID] = None
    ) -> Device:
        """Register a token, or refresh it if the app relaunches (T-06.2).

        Uniqueness is (user_id, push_token): a relaunch re-sends the same
        token, so we update the existing row's last_seen/platform instead
        of inserting a duplicate.
        """
        existing = await self.get_by_token(user_id, payload.push_token)
        if existing:
            existing.platform = payload.platform
            existing.provider = payload.provider
            await self.db.execute(
                update(Device)
                .where(Device.id == existing.id)
                .values(
                    platform=payload.platform,
                    provider=payload.provider,
                    tenant_id=tenant_id,
                )
            )
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        device = Device(
            user_id=user_id,
            tenant_id=tenant_id,
            platform=payload.platform,
            push_token=payload.push_token,
            provider=payload.provider,
        )
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def get_by_token(self, user_id: UUID, push_token: str) -> Optional[Device]:
        stmt = select(Device).where(
            Device.user_id == user_id, Device.push_token == push_token
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> List[Device]:
        stmt = select(Device).where(Device.user_id == user_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_token(self, user_id: UUID, push_token: str) -> bool:
        """Unregister one token (logout). Returns whether a row was removed."""
        result = await self.db.execute(
            sa_delete(Device).where(
                Device.user_id == user_id, Device.push_token == push_token
            )
        )
        await self.db.commit()
        return (result.rowcount or 0) > 0

    async def prune_tokens(self, tokens: List[str]) -> int:
        """Drop rows whose tokens the provider reported invalid (T-06.6)."""
        if not tokens:
            return 0
        result = await self.db.execute(
            sa_delete(Device).where(Device.push_token.in_(tokens))
        )
        await self.db.commit()
        return result.rowcount or 0
