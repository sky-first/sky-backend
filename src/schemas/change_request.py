"""ChangeRequest schemas — chat ↔ widget bridge wire shapes.

See chat-threads-master-plan PR3.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChangeRequestCreate(BaseModel):
    """Payload to open a change-request from inside a comment flow.

    The FE creates the comment first (so the message_id exists) and then
    creates the change-request pointing at that message + the target
    widget. Typical chain:

      POST /conversations/{conv}/messages  →  message_id
      POST /change-requests                 ← uses message_id + widget_id
    """

    widget_id: UUID
    conversation_id: UUID
    message_id: UUID
    content: str = Field(..., min_length=1, max_length=100_000)


class ChangeRequestResponse(BaseModel):
    id: UUID
    widget_id: UUID
    conversation_id: UUID
    message_id: UUID
    requester_id: Optional[UUID]
    status: str
    content: str
    created_at: datetime
    resolved_at: Optional[datetime]
    resolved_by: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class ChangeRequestListResponse(BaseModel):
    items: List[ChangeRequestResponse]
    pending_count: int
