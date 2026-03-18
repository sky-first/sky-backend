"""File upload repository."""

from typing import List
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.file import FileUpload, SyncLog
from src.repositories.base import BaseRepository


class FileUploadRepository(BaseRepository[FileUpload]):
    """File upload repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, FileUpload)


class SyncLogRepository(BaseRepository[SyncLog]):
    """Sync log repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, SyncLog)

    async def get_by_connection_id(
        self, connection_id: UUID, limit: int = 30
    ) -> List[SyncLog]:
        """Get sync logs for a connection."""
        query = (
            select(SyncLog)
            .where(SyncLog.connection_id == connection_id)
            .order_by(desc(SyncLog.started_at))
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
