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

    async def get_by_space(self, space_id: UUID, skip: int = 0, limit: int = 100) -> List[Crew]:
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

    async def get_by_id_including_deleted(self, id: UUID) -> Optional[Crew]:
        """
        Get entity by ID including deleted ones.
        Used for delete operations where we need to find the entity even if it's soft-deleted.

        Args:
            id: Entity ID

        Returns:
            Optional[Crew]: Entity or None
        """
        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[dict] = None,
        order_by: Optional[str] = None,
    ) -> List[Crew]:
        """
        Get all crews with pagination, excluding soft-deleted ones.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            filters: Optional filters (dict of column: value)
            order_by: Optional column name to order by

        Returns:
            List[Crew]: List of crews (excluding deleted)
        """
        query = select(self.model).where(self.model.deleted_at.is_(None))

        # Apply filters
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        # Apply ordering
        if order_by and hasattr(self.model, order_by):
            query = query.order_by(getattr(self.model, order_by))
        else:
            # Default ordering by created_at desc
            query = query.order_by(self.model.created_at.desc())

        # Apply pagination
        query = query.offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())


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
        from sqlalchemy.orm import selectinload

        result = await self.db.execute(
            select(CrewMember)
            .where(CrewMember.crew_id == crew_id)
            .options(selectinload(CrewMember.user))
        )
        return list(result.scalars().all())

    async def get_by_crew_and_user(self, crew_id: UUID, user_id: UUID) -> Optional[CrewMember]:
        """
        Get crew member by crew and user.

        Args:
            crew_id: Crew ID
            user_id: User ID

        Returns:
            Optional[CrewMember]: Crew member or None
        """
        result = await self.db.execute(
            select(CrewMember).where(CrewMember.crew_id == crew_id, CrewMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_crew_ids_by_user_and_space(self, user_id: UUID, space_id: UUID) -> List[UUID]:
        """
        Get crew IDs where user is a member and crew belongs to the specified space.

        Args:
            user_id: User ID
            space_id: Space ID

        Returns:
            List[UUID]: List of crew IDs
        """
        result = await self.db.execute(
            select(CrewMember.crew_id)
            .join(Crew, CrewMember.crew_id == Crew.id)
            .where(
                CrewMember.user_id == user_id,
                Crew.space_id == space_id,
                Crew.deleted_at.is_(None),
            )
            .distinct()
        )
        return [row[0] for row in result.all()]

    async def get_crew_ids_by_user(self, user_id: UUID) -> List[UUID]:
        """
        Get all crew IDs where user is a member (across all spaces).

        This is especially useful for Personal mode, where the user can access
        all crews they're associated with, regardless of the currently selected space.
        """
        result = await self.db.execute(
            select(CrewMember.crew_id)
            .join(Crew, CrewMember.crew_id == Crew.id)
            .where(
                CrewMember.user_id == user_id,
                Crew.deleted_at.is_(None),
            )
            .distinct()
        )
        return [row[0] for row in result.all()]
