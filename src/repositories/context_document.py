"""Context Document repository — CRUD + scope-aware queries.

Phase 2.1 deliverable. Embedding read/write is NOT handled here — that
happens in the AI service after the document is rendered and embedded.
This repository stores everything *except* the vector; the AI service
updates `embedding` + `indexed_at` via a separate write path.
"""

from datetime import datetime
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.context_document import ContextDocument
from src.repositories.base import BaseRepository


class ContextDocumentRepository(BaseRepository[ContextDocument]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, ContextDocument)

    async def upsert(
        self,
        *,
        kind: str,
        source_table: str,
        source_id: UUID,
        title: str,
        body: str,
        metadata: Optional[dict] = None,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        owner_user_id: Optional[UUID] = None,
        visibility: str = "space",
        pii_flags: Optional[Iterable[str]] = None,
        language: str = "pt",
    ) -> ContextDocument:
        """Insert-or-update a document by (source_table, source_id).

        The embedding is not touched — ingestion writes it separately after
        the document has been rendered. On re-upsert the `indexed_at` is
        cleared so the ingest worker re-embeds the new body.
        """
        existing = await self.get_by_source(source_table, source_id)
        now = datetime.utcnow()
        if existing is not None:
            existing.kind = kind
            existing.title = title
            existing.body = body
            existing.meta = dict(metadata or {})
            existing.space_id = space_id
            existing.crew_id = crew_id
            existing.owner_user_id = owner_user_id
            existing.visibility = visibility
            existing.pii_flags = list(pii_flags or [])
            existing.language = language
            existing.updated_at = now
            existing.indexed_at = None
            existing.deleted_at = None
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        doc = ContextDocument(
            kind=kind,
            source_table=source_table,
            source_id=source_id,
            title=title,
            body=body,
            meta=dict(metadata or {}),
            space_id=space_id,
            crew_id=crew_id,
            owner_user_id=owner_user_id,
            visibility=visibility,
            pii_flags=list(pii_flags or []),
            language=language,
            created_at=now,
            updated_at=now,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def get_by_source(
        self, source_table: str, source_id: UUID
    ) -> Optional[ContextDocument]:
        result = await self.db.execute(
            select(ContextDocument).where(
                and_(
                    ContextDocument.source_table == source_table,
                    ContextDocument.source_id == source_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete_by_source(
        self, source_table: str, source_id: UUID
    ) -> bool:
        """Soft-delete mirrors the source row disappearing.

        We never hard-delete — the evidence trail on past `agent_runs` must
        still be able to cite what was known at the time.
        """
        now = datetime.utcnow()
        result = await self.db.execute(
            update(ContextDocument)
            .where(
                and_(
                    ContextDocument.source_table == source_table,
                    ContextDocument.source_id == source_id,
                    ContextDocument.deleted_at.is_(None),
                )
            )
            .values(deleted_at=now, updated_at=now)
        )
        return result.rowcount > 0

    async def list_in_scope(
        self,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        kind: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[ContextDocument]:
        stmt = select(ContextDocument)
        clauses = []
        if space_id is not None:
            clauses.append(ContextDocument.space_id == space_id)
        if crew_id is not None:
            clauses.append(ContextDocument.crew_id == crew_id)
        if kind is not None:
            clauses.append(ContextDocument.kind == kind)
        if not include_deleted:
            clauses.append(ContextDocument.deleted_at.is_(None))
        if clauses:
            stmt = stmt.where(and_(*clauses))
        stmt = stmt.order_by(ContextDocument.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
