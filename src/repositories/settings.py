"""Settings repositories."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.permission import APIKey, Integration
from src.repositories.base import BaseRepository


class APIKeyRepository(BaseRepository[APIKey]):
    """API key repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, APIKey)

    async def get_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[APIKey]:
        """
        Get API keys by user.

        Args:
            user_id: User ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[APIKey]: List of API keys
        """
        result = await self.db.execute(
            select(APIKey)
            .where(APIKey.user_id == user_id, APIKey.revoked_at.is_(None))
            .order_by(APIKey.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())


class IntegrationRepository(BaseRepository[Integration]):
    """Integration repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Integration)

    async def get_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Integration]:
        """
        Get integrations by user.

        Args:
            user_id: User ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Integration]: List of integrations
        """
        result = await self.db.execute(
            select(Integration)
            .where(Integration.user_id == user_id)
            .order_by(Integration.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_type(
        self, user_id: UUID, integration_type: str
    ) -> Optional[Integration]:
        """
        Get integration by type.

        Args:
            user_id: User ID
            integration_type: Integration type

        Returns:
            Optional[Integration]: Integration or None
        """
        result = await self.db.execute(
            select(Integration).where(
                Integration.user_id == user_id, Integration.type == integration_type
            )
        )
        return result.scalar_one_or_none()

