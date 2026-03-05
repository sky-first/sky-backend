"""Enterprise Relationship repository."""

from typing import List
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.enterprise_relationship import EnterpriseRelationship
from src.repositories.base import BaseRepository


class EnterpriseRelationshipRepository(BaseRepository[EnterpriseRelationship]):
    """Enterprise Relationship repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, EnterpriseRelationship)

    async def get_by_user(self, user_id: UUID) -> List[EnterpriseRelationship]:
        """Get relationships by user."""
        query = (
            select(EnterpriseRelationship)
            .where(EnterpriseRelationship.created_by == user_id)
            .order_by(EnterpriseRelationship.created_at.desc())
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())
