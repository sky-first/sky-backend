"""Space repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.connection import DataConnection
from src.models.crew import Crew
from src.models.space import Space, SpaceConnection, SpaceMember
from src.repositories.base import BaseRepository


class SpaceRepository(BaseRepository[Space]):
    """Space repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Space)

    async def get_by_user(self, user_id: UUID, skip: int = 0, limit: int = 100) -> List[Space]:
        """
        Get spaces by user.

        Args:
            user_id: User ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Space]: List of spaces
        """
        result = await self.db.execute(
            select(Space)
            .where(Space.created_by == user_id, Space.deleted_at.is_(None))
            .order_by(Space.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, id: UUID) -> Optional[Space]:
        """
        Get entity by ID. Overridden to include deleted_at filter.

        Args:
            id: Entity ID

        Returns:
            Optional[Space]: Entity or None
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id, self.model.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_space_crews(self, space_id: UUID) -> List[Crew]:
        """
        Get crews for a space.

        Args:
            space_id: Space ID

        Returns:
            List[Crew]: List of crews
        """
        result = await self.db.execute(
            select(Crew).where(Crew.space_id == space_id, Crew.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_space_connections(self, space_id: UUID) -> List[SpaceConnection]:
        """
        Get connections for a space.

        Args:
            space_id: Space ID

        Returns:
            List[SpaceConnection]: List of space connections
        """
        result = await self.db.execute(
            # Filter out stale references (space_connections pointing to deleted/missing connections)
            select(SpaceConnection)
            .join(DataConnection, SpaceConnection.connection_id == DataConnection.id)
            .where(
                SpaceConnection.space_id == space_id,
                DataConnection.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())


class SpaceMemberRepository(BaseRepository[SpaceMember]):
    """Space member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, SpaceMember)

    async def get_by_space_and_user(self, space_id: UUID, user_id: UUID) -> Optional[SpaceMember]:
        """
        Get space member by space and user.

        Args:
            space_id: Space ID
            user_id: User ID

        Returns:
            Optional[SpaceMember]: Member or None
        """
        result = await self.db.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_space_members(self, space_id: UUID) -> List[SpaceMember]:
        """
        Get all members of a space.

        Args:
            space_id: Space ID

        Returns:
            List[SpaceMember]: List of members
        """
        result = await self.db.execute(
            select(SpaceMember)
            .where(SpaceMember.space_id == space_id)
            .options(selectinload(SpaceMember.user))
        )
        return list(result.scalars().all())
