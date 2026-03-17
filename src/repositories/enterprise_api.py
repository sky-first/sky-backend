"""Enterprise API repository."""

from typing import List
from uuid import UUID

from sqlalchemy import select

from src.models.enterprise_api import EnterpriseAPI
from src.repositories.base import BaseRepository


class EnterpriseAPIRepository(BaseRepository[EnterpriseAPI]):
    """Enterprise API repository."""

    def __init__(self, db):
        super().__init__(db, EnterpriseAPI)

    async def get_by_user(self, user_id: UUID) -> List[EnterpriseAPI]:
        """
        Get all APIs created by a user.

        Args:
            user_id: User ID

        Returns:
            List[EnterpriseAPI]: List of APIs
        """
        result = await self.db.execute(
            select(self.model).where(self.model.created_by == user_id)
        )
        return list(result.scalars().all())
