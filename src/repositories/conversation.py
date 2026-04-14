"""Conversation repository — SQL-level access for the chat thread tables."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.conversation import Conversation
from src.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """CRUD + scoped queries on conversations."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Conversation)

    async def create(
        self,
        *,
        page_id: UUID,
        created_by: UUID,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        title: Optional[str] = None,
    ) -> Conversation:
        # Explicit microsecond timestamps. The server_default
        # CURRENT_TIMESTAMP on SQLite only gives second precision, which
        # breaks cursor-paginated ordering when multiple rows land in the
        # same second. Production PostgreSQL has microsecond precision
        # natively so this is only ever a factor in tests, but we don't want
        # tests to hide real bugs either.
        now = datetime.utcnow()
        conv = Conversation(
            page_id=page_id,
            space_id=space_id,
            crew_id=crew_id,
            created_by=created_by,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conv)
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def list_for_page(
        self,
        *,
        page_id: UUID,
        user_id: UUID,
        user_space_ids: List[UUID],
        user_crew_ids: List[UUID],
        include_archived: bool = False,
        limit: int = 20,
        cursor: Optional[datetime] = None,
    ) -> List[Conversation]:
        """Return conversations on `page_id` visible to the given user.

        Visibility rules (same semantics as the service layer — duplicated here
        so the DB filter is tight):
          - personal (no space_id, no crew_id) → only if created_by == user
          - space-scoped → if space_id in user_space_ids
          - crew-scoped → if crew_id in user_crew_ids
        """
        conditions = [Conversation.page_id == page_id]
        if not include_archived:
            conditions.append(Conversation.archived_at.is_(None))

        visibility = or_(
            # personal — only creator sees
            and_(
                Conversation.space_id.is_(None),
                Conversation.crew_id.is_(None),
                Conversation.created_by == user_id,
            ),
            # space-scoped
            Conversation.space_id.in_(user_space_ids) if user_space_ids else False,
            # crew-scoped
            Conversation.crew_id.in_(user_crew_ids) if user_crew_ids else False,
        )
        conditions.append(visibility)

        if cursor is not None:
            conditions.append(Conversation.updated_at < cursor)

        # Stable order: updated_at desc, id desc as tiebreaker when many
        # conversations share the same second-level timestamp (SQLite).
        stmt = (
            select(Conversation)
            .where(and_(*conditions))
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, conversation_id: UUID, **fields) -> Optional[Conversation]:
        conv = await self.get_by_id(conversation_id)
        if not conv:
            return None
        for k, v in fields.items():
            setattr(conv, k, v)
        conv.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def archive(self, conversation_id: UUID) -> Optional[Conversation]:
        conv = await self.get_by_id(conversation_id)
        if not conv:
            return None
        conv.archived_at = datetime.utcnow()
        conv.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def unarchive(self, conversation_id: UUID) -> Optional[Conversation]:
        conv = await self.get_by_id(conversation_id)
        if not conv:
            return None
        conv.archived_at = None
        conv.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def delete(self, conversation_id: UUID) -> bool:
        conv = await self.get_by_id(conversation_id)
        if not conv:
            return False
        await self.db.delete(conv)
        await self.db.flush()
        return True
