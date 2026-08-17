"""Message repository — access layer for messages inside a conversation."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.conversation import Message
from src.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """CRUD + scoped queries on messages."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Message)

    async def create(
        self,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        kind: Optional[str] = None,
        user_id: Optional[UUID] = None,
        query_id: Optional[UUID] = None,
        cost_tokens: Optional[int] = None,
        cost_usd: Optional[Decimal] = None,
        tier: Optional[str] = None,
        duration_ms: Optional[int] = None,
        parent_message_id: Optional[UUID] = None,
        incorporated_in_message_id: Optional[UUID] = None,
        finding_id: Optional[UUID] = None,
    ) -> Message:
        # Explicit microsecond timestamp — see conversation repo for the
        # SQLite precision rationale.
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            kind=kind,
            content=content,
            user_id=user_id,
            query_id=query_id,
            cost_tokens=cost_tokens,
            cost_usd=cost_usd,
            tier=tier,
            duration_ms=duration_ms,
            created_at=datetime.utcnow(),
            parent_message_id=parent_message_id,
            incorporated_in_message_id=incorporated_in_message_id,
            finding_id=finding_id,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def list_for_conversation(
        self,
        *,
        conversation_id: UUID,
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> List[Message]:
        conditions = [Message.conversation_id == conversation_id]
        if cursor is not None:
            # Keyset: return messages strictly newer than cursor so the
            # client can paginate forward through the thread.
            conditions.append(Message.created_at > cursor)
        stmt = (
            select(Message)
            .where(and_(*conditions))
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_pinned_widget(self, message_id: UUID, widget_id: UUID) -> Optional[Message]:
        msg = await self.get_by_id(message_id)
        if not msg:
            return None
        msg.pinned_widget_id = widget_id
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def list_pending_comments(self, *, conversation_id: UUID) -> List[Message]:
        """Return comments posted after the last ai_response (or since the
        thread started, if no AI has replied yet), excluding comments that
        are already marked incorporated into a previous AI bundle.

        Used by the Ask-AI bundling flow (chat-threads-master-plan PR2):
        when the owner fires a new question, every unincorporated comment
        since the last AI answer is pulled into the prompt and then
        stamped with `incorporated_in_message_id` pointing at the new AI
        response.
        """
        # Last ai_response in the thread (if any).
        last_ai_stmt = (
            select(Message.created_at)
            .where(
                Message.conversation_id == conversation_id,
                Message.kind == "ai_response",
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_ai_row = await self.db.execute(last_ai_stmt)
        last_ai_at = last_ai_row.scalar_one_or_none()

        conditions = [
            Message.conversation_id == conversation_id,
            Message.kind == "comment",
            Message.incorporated_in_message_id.is_(None),
        ]
        if last_ai_at is not None:
            conditions.append(Message.created_at > last_ai_at)

        stmt = (
            select(Message)
            .where(and_(*conditions))
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_incorporated(self, *, message_ids: List[UUID], ai_response_id: UUID) -> None:
        """Stamp the given comments with the AI response that bundled them.

        Used by the Ask-AI flow after the AI replies. FE renders the
        "incorporated in #N" badge from this column.
        """
        if not message_ids:
            return
        from sqlalchemy import update as _update

        await self.db.execute(
            _update(Message)
            .where(Message.id.in_(message_ids))
            .values(incorporated_in_message_id=ai_response_id)
        )
        await self.db.flush()

    async def list_up_to(self, *, conversation_id: UUID, until_message_id: UUID) -> List[Message]:
        """Return every message in the conversation up to and including the
        given message, in chronological order.

        Used for forking: the new thread inherits all messages prior to the
        branch point so the user retains context when continuing separately.
        """
        until = await self.get_by_id(until_message_id)
        if until is None or until.conversation_id != conversation_id:
            return []
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at <= until.created_at,
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
