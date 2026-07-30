"""Conversation schemas — request/response shapes for the chat thread API."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    """Payload to open a new conversation on a page.

    space_id and crew_id are optional. Their combination determines visibility:
      - both None          → personal conversation, visible only to the creator
      - space_id set       → visible to all members of the space
      - crew_id set        → visible to all members of the crew
      - both set           → crew within a space; crew visibility wins
    """

    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    # Chat session ("Chat 1", "Chat 2", …) this thread belongs to. When
    # omitted the service falls back to the page's default session so the
    # thread always lands in a session the switcher can show.
    session_id: Optional[UUID] = None


class ConversationUpdate(BaseModel):
    """Partial update. Only the title is editable via this endpoint."""

    title: Optional[str] = Field(None, max_length=500)


class TransferOwnershipRequest(BaseModel):
    """Move thread ownership from the current owner to another member.

    Authorised callers: the current thread owner, or a space admin/editor
    (covers HR off-boarding flows). The BE writes an audit log entry
    capturing the previous owner, the new owner and the actor.
    """

    new_owner_id: UUID


class ConversationResponse(BaseModel):
    """Full conversation state returned to the frontend."""

    id: UUID
    page_id: UUID
    space_id: Optional[UUID]
    crew_id: Optional[UUID]
    session_id: Optional[UUID] = None
    title: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime]
    # chat-threads-master-plan PR1, 2026-05-20
    resolved_at: Optional[datetime] = None
    pinned_message_id: Optional[UUID] = None
    # BE-04 (Sky Mobile) — derived voice/text icon for the History row: 'voice'
    # when the thread contains any spoken message, else 'text'. Stamped by the
    # list endpoint (not a stored column); defaults to 'text'.
    origin: str = "text"

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    """Paged list of conversations."""

    items: List[ConversationResponse]
    # next_cursor is the `updated_at` of the last item in the page; the client
    # sends it back as `cursor` on the next call. None means this is the last
    # page.
    next_cursor: Optional[datetime] = None
