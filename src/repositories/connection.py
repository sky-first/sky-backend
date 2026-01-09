"""Connection repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.connection import ConnectionMetadata, DataConnection
from src.repositories.base import BaseRepository


class ConnectionRepository(BaseRepository[DataConnection]):
    """Connection repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, DataConnection)

    async def get_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100, filters: Optional[dict] = None
    ) -> List[DataConnection]:
        """
        Get connections by user.

        Args:
            user_id: User ID
            skip: Number of records to skip
            limit: Maximum number of records
            filters: Additional filters

        Returns:
            List[DataConnection]: List of connections
        """
        query = select(DataConnection).where(
            DataConnection.created_by == user_id, DataConnection.deleted_at.is_(None)
        )

        if filters:
            if "status" in filters:
                query = query.where(DataConnection.status == filters["status"])
            if "connector_id" in filters:
                query = query.where(DataConnection.connector_id == filters["connector_id"])

        query = query.order_by(DataConnection.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, id: UUID) -> Optional[DataConnection]:
        """
        Get entity by ID. Overridden to include deleted_at filter.

        Args:
            id: Entity ID

        Returns:
            Optional[DataConnection]: Entity or None
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id, self.model.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()


class ConnectionMetadataRepository(BaseRepository[ConnectionMetadata]):
    """Connection metadata repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ConnectionMetadata)

    async def get_by_connection_id(self, connection_id: UUID) -> Optional[ConnectionMetadata]:
        """
        Get metadata by connection ID.

        Args:
            connection_id: Connection ID

        Returns:
            Optional[ConnectionMetadata]: Metadata or None
        """
        result = await self.db.execute(
            select(ConnectionMetadata).where(ConnectionMetadata.connection_id == connection_id)
        )
        return result.scalar_one_or_none()
