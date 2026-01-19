"""Comment schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CommentBase(BaseModel):
    """Base comment schema."""

    content: str
    dashboard_id: UUID
    widget_id: Optional[UUID] = None
    mentions: List[UUID] = []


class CommentCreate(CommentBase):
    """Schema for creating a comment."""
    pass


class CommentResponse(CommentBase):
    """Schema for comment response."""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
