"""Permission repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.permission import ConnectionPermission, TableMemberPermission
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


class TableMemberPermissionRepository(BaseRepository[TableMemberPermission]):
    """Table member permission repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, TableMemberPermission)

    async def get_by_table(
        self, connection_id: UUID, table_name: str
    ) -> List[TableMemberPermission]:
        """
        Get permissions by connection and table.

        Args:
            connection_id: Connection ID
            table_name: Table name

        Returns:
            List[TableMemberPermission]: List of permissions
        """
        try:
            result = await self.db.execute(
                select(TableMemberPermission).where(
                    TableMemberPermission.connection_id == connection_id,
                    TableMemberPermission.table_name == table_name,
                )
            )
            return list(result.scalars().all())
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error fetching table member permissions: connection_id={connection_id}, table_name={table_name}, error={e}")
            raise

    async def get_by_member(
        self, member_id: UUID
    ) -> List[TableMemberPermission]:
        """
        Get permissions by member ID.

        Args:
            member_id: Member ID

        Returns:
            List[TableMemberPermission]: List of permissions
        """
        result = await self.db.execute(
            select(TableMemberPermission).where(TableMemberPermission.member_id == member_id)
        )
        return list(result.scalars().all())

    async def get_by_connection_table_member(
        self, connection_id: UUID, table_name: str, member_id: UUID
    ) -> Optional[TableMemberPermission]:
        """
        Get permission by connection, table, and member.

        Args:
            connection_id: Connection ID
            table_name: Table name
            member_id: Member ID

        Returns:
            Optional[TableMemberPermission]: Permission or None
        """
        result = await self.db.execute(
            select(TableMemberPermission).where(
                TableMemberPermission.connection_id == connection_id,
                TableMemberPermission.table_name == table_name,
                TableMemberPermission.member_id == member_id,
            )
        )
        return result.scalar_one_or_none()

