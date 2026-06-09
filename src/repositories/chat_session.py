"""ChatSession repository — data access for page-scoped chat sessions."""

from typing import List
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from src.models.chat_session import ChatSession
from src.repositories.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    def __init__(self, db):
        super().__init__(db, ChatSession)

    async def list_for_page(
        self,
        *,
        page_id: UUID,
        user_id: UUID,
        user_space_ids: List[UUID],
        user_crew_ids: List[UUID],
        include_archived: bool = False,
    ) -> List[ChatSession]:
        """Sessions on ``page_id`` visible to the user, ordered for the switcher.

        Same visibility model as conversations: personal sessions are seen
        only by their creator; space/crew sessions by any member.
        """
        conditions = [ChatSession.page_id == page_id]
        if not include_archived:
            conditions.append(ChatSession.archived_at.is_(None))

        visibility = or_(
            and_(
                ChatSession.space_id.is_(None),
                ChatSession.crew_id.is_(None),
                ChatSession.created_by == user_id,
            ),
            ChatSession.space_id.in_(user_space_ids) if user_space_ids else False,
            ChatSession.crew_id.in_(user_crew_ids) if user_crew_ids else False,
        )
        conditions.append(visibility)

        stmt = (
            select(ChatSession)
            .where(and_(*conditions))
            .order_by(ChatSession.position.asc(), ChatSession.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_for_page(self, page_id: UUID) -> int:
        """Total sessions on a page (incl. archived)."""
        stmt = select(func.count()).select_from(ChatSession).where(
            ChatSession.page_id == page_id
        )
        return int((await self.db.execute(stmt)).scalar() or 0)

    async def max_position_for_page(self, page_id: UUID) -> int:
        """Highest ``position`` on a page, or -1 when the page has none.

        Drives MONOTONIC "Chat N" naming + ordering: a new chat is always
        ``max + 1`` so numbers are never reused after a delete (which would
        otherwise produce two "Chat 3" on the same page).
        """
        stmt = select(func.max(ChatSession.position)).where(
            ChatSession.page_id == page_id
        )
        result = (await self.db.execute(stmt)).scalar()
        return int(result) if result is not None else -1
