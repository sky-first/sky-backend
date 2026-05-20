"""Message schemas — request/response shapes for messages inside a conversation."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    """Payload to append a message to a conversation.

    Callers can only create messages with role='user'. Assistant / system
    messages are produced internally (by the AI service callback in Phase 2,
    or by the agent runtime). The validator below rejects anything else.
    """

    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=100_000)
    query_id: Optional[UUID] = None
    cost_tokens: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[Decimal] = Field(None, ge=0)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    query_id: Optional[UUID]
    cost_tokens: Optional[int]
    cost_usd: Optional[Decimal]
    created_at: datetime
    pinned_widget_id: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    # Messages paginate by created_at ascending (oldest first) so the
    # frontend can render them in thread order without reversing.
    next_cursor: Optional[datetime] = None


class PinRequest(BaseModel):
    """Materialise a widget pinned to this message."""

    page_id: UUID
    title: Optional[str] = Field(None, max_length=255)
    widget_type: str = Field(default="insight", max_length=50)
    position: Optional[dict] = None  # {x, y}
    size: Optional[dict] = None      # {width, height}


class ForkRequest(BaseModel):
    """Branch a conversation from a specific message."""

    from_message_id: UUID
