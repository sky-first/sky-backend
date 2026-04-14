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
        query_id: Optional[UUID] = None,
        cost_tokens: Optional[int] = None,
        cost_usd: Optional[Decimal] = None,
    ) -> Message:
        # Explicit microsecond timestamp — see conversation repo for the
        # SQLite precision rationale.
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            query_id=query_id,
            cost_tokens=cost_tokens,
            cost_usd=cost_usd,
            created_at=datetime.utcnow(),
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

    async def set_pinned_widget(
        self, message_id: UUID, widget_id: UUID
    ) -> Optional[Message]:
        msg = await self.get_by_id(message_id)
        if not msg:
            return None
        msg.pinned_widget_id = widget_id
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def list_up_to(
        self, *, conversation_id: UUID, until_message_id: UUID
    ) -> List[Message]:
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
