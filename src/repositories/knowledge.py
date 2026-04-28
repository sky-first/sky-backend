"""Knowledge Library repositories."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge import KnowledgeFile, KnowledgeFileChunk, KnowledgeQuotaUsage
from src.repositories.base import BaseRepository


class KnowledgeFileRepository(BaseRepository[KnowledgeFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, KnowledgeFile)

    async def list_by_scope(
        self,
        scope: str,
        scope_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[KnowledgeFile]:
        q = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.scope == scope,
                KnowledgeFile.scope_id == scope_id,
                KnowledgeFile.deleted_at.is_(None),
            )
            .order_by(KnowledgeFile.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_personal(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[KnowledgeFile]:
        q = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.scope == "personal",
                KnowledgeFile.user_id == user_id,
                KnowledgeFile.deleted_at.is_(None),
            )
            .order_by(KnowledgeFile.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def search_by_name(
        self,
        query: str,
        scope: str,
        scope_id: Optional[UUID],
        user_id: Optional[UUID],
        limit: int = 10,
    ) -> List[KnowledgeFile]:
        """Typeahead search for @mention dropdown."""
        q = select(KnowledgeFile).where(
            KnowledgeFile.status == "ready",
            KnowledgeFile.deleted_at.is_(None),
            KnowledgeFile.original_name.ilike(f"%{query}%"),
        )
        if scope == "personal":
            q = q.where(KnowledgeFile.user_id == user_id, KnowledgeFile.scope == "personal")
        else:
            q = q.where(KnowledgeFile.scope == scope, KnowledgeFile.scope_id == scope_id)
        result = await self.db.execute(q.limit(limit))
        return list(result.scalars().all())

    async def soft_delete(self, file_id: UUID) -> None:
        from sqlalchemy import update

        await self.db.execute(
            update(KnowledgeFile)
            .where(KnowledgeFile.id == file_id)
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await self.db.flush()

    async def count_by_scope(self, scope: str, scope_id: UUID) -> int:
        q = select(func.count()).select_from(KnowledgeFile).where(
            KnowledgeFile.scope == scope,
            KnowledgeFile.scope_id == scope_id,
            KnowledgeFile.deleted_at.is_(None),
        )
        result = await self.db.execute(q)
        return result.scalar() or 0


class KnowledgeChunkRepository(BaseRepository[KnowledgeFileChunk]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, KnowledgeFileChunk)

    async def delete_by_file(self, file_id: UUID) -> None:
        from sqlalchemy import delete

        await self.db.execute(
            delete(KnowledgeFileChunk).where(KnowledgeFileChunk.file_id == file_id)
        )
        await self.db.flush()


class QuotaRepository(BaseRepository[KnowledgeQuotaUsage]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, KnowledgeQuotaUsage)

    async def get_or_create(self, scope: str, scope_id: UUID) -> KnowledgeQuotaUsage:
        q = select(KnowledgeQuotaUsage).where(
            KnowledgeQuotaUsage.scope == scope,
            KnowledgeQuotaUsage.scope_id == scope_id,
        )
        result = await self.db.execute(q)
        row = result.scalar_one_or_none()
        if row:
            return row
        row = await self.create(scope=scope, scope_id=scope_id, bytes_used=0, files_count=0)
        return row

    async def get_for_update(self, scope: str, scope_id: UUID) -> KnowledgeQuotaUsage:
        """Lock row for atomic quota enforcement."""
        from sqlalchemy import text

        result = await self.db.execute(
            select(KnowledgeQuotaUsage)
            .where(
                KnowledgeQuotaUsage.scope == scope,
                KnowledgeQuotaUsage.scope_id == scope_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if not row:
            row = await self.create(scope=scope, scope_id=scope_id, bytes_used=0, files_count=0)
        return row

    async def increment(self, scope: str, scope_id: UUID, bytes_delta: int, files_delta: int) -> None:
        from sqlalchemy import update

        await self.db.execute(
            update(KnowledgeQuotaUsage)
            .where(
                KnowledgeQuotaUsage.scope == scope,
                KnowledgeQuotaUsage.scope_id == scope_id,
            )
            .values(
                bytes_used=KnowledgeQuotaUsage.bytes_used + bytes_delta,
                files_count=KnowledgeQuotaUsage.files_count + files_delta,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()
