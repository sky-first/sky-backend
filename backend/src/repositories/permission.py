"""Permission repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.permission import ConnectionPermission
from src.repositories.base import BaseRepository


class PermissionRepository(BaseRepository[ConnectionPermission]):
    """Permission repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ConnectionPermission)

    async def get_by_connection_id(self, connection_id: UUID) -> List[ConnectionPermission]:
        """
        Get permissions by connection ID.

        Args:
            connection_id: Connection ID

        Returns:
            List[ConnectionPermission]: List of permissions
        """
        result = await self.db.execute(
            select(ConnectionPermission).where(ConnectionPermission.connection_id == connection_id)
        )
        return list(result.scalars().all())

    async def get_by_space_id(self, space_id: UUID) -> List[ConnectionPermission]:
        """
        Get permissions by space ID.

        Args:
            space_id: Space ID

        Returns:
            List[ConnectionPermission]: List of permissions
        """
        result = await self.db.execute(
            select(ConnectionPermission).where(ConnectionPermission.space_id == space_id)
        )
        return list(result.scalars().all())

    async def get_by_crew_id(self, crew_id: UUID) -> List[ConnectionPermission]:
        """
        Get permissions by crew ID.

        Args:
            crew_id: Crew ID

        Returns:
            List[ConnectionPermission]: List of permissions
        """
        result = await self.db.execute(
            select(ConnectionPermission).where(ConnectionPermission.crew_id == crew_id)
        )
        return list(result.scalars().all())

    async def get_by_connection_and_space(
        self, connection_id: UUID, space_id: Optional[UUID], crew_id: Optional[UUID]
    ) -> Optional[ConnectionPermission]:
        """
        Get permission by connection, space, and crew.

        Args:
            connection_id: Connection ID
            space_id: Space ID (optional)
            crew_id: Crew ID (optional)

        Returns:
            Optional[ConnectionPermission]: Permission or None
        """
        query = select(ConnectionPermission).where(ConnectionPermission.connection_id == connection_id)

        if space_id:
            query = query.where(ConnectionPermission.space_id == space_id)
        else:
            query = query.where(ConnectionPermission.space_id.is_(None))

        if crew_id:
            query = query.where(ConnectionPermission.crew_id == crew_id)
        else:
            query = query.where(ConnectionPermission.crew_id.is_(None))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

