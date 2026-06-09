"""ChatSession schemas — request/response shapes for the chat-session API."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    """Payload to open a new chat session ("+") on a page.

    ``title`` is optional — the service assigns "Chat N" when omitted.
    ``space_id`` / ``crew_id`` are normally inherited from the page; clients
    may pin them but the service overrides with the page's scope so a
    session on a shared page is always visible to every member.
    """

    title: Optional[str] = Field(None, max_length=500)
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None


class ChatSessionUpdate(BaseModel):
    """Partial update. Only the title is editable via this endpoint."""

    title: Optional[str] = Field(None, max_length=500)


class ChatSessionResponse(BaseModel):
    """Full chat-session state returned to the frontend."""

    id: UUID
    page_id: UUID
    space_id: Optional[UUID]
    crew_id: Optional[UUID]
    title: Optional[str]
    position: int
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChatSessionListResponse(BaseModel):
    """All chat sessions on a page, ordered for the switcher."""

    items: List[ChatSessionResponse]
