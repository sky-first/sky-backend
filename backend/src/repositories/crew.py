"""Crew repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import Crew, CrewMember
from src.repositories.base import BaseRepository


class CrewRepository(BaseRepository[Crew]):
    """Crew repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Crew)

    async def get_by_space(
        self, space_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Crew]:
        """
        Get crews by space.

        Args:
            space_id: Space ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Crew]: List of crews
        """
        result = await self.db.execute(
            select(Crew)
            .where(Crew.space_id == space_id, Crew.deleted_at.is_(None))
            .order_by(Crew.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, id: UUID) -> Optional[Crew]:
        """
        Get entity by ID. Overridden to include deleted_at filter.

        Args:
            id: Entity ID

        Returns:
            Optional[Crew]: Entity or None
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id, self.model.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()


class CrewMemberRepository(BaseRepository[CrewMember]):
    """Crew member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, CrewMember)

    async def get_by_crew(self, crew_id: UUID) -> List[CrewMember]:
        """
        Get members by crew.

        Args:
            crew_id: Crew ID

        Returns:
            List[CrewMember]: List of crew members
        """
        result = await self.db.execute(
            select(CrewMember).where(CrewMember.crew_id == crew_id)
        )
        return list(result.scalars().all())

    async def get_by_crew_and_user(
        self, crew_id: UUID, user_id: UUID
    ) -> Optional[CrewMember]:
        """
        Get crew member by crew and user.

        Args:
            crew_id: Crew ID
            user_id: User ID

        Returns:
            Optional[CrewMember]: Crew member or None
        """
        result = await self.db.execute(
            select(CrewMember).where(
                CrewMember.crew_id == crew_id, CrewMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

