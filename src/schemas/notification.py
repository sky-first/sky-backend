"""Notification schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.notification import NotificationType


class NotificationBase(BaseModel):
    """Base notification schema."""
    
    type: NotificationType
    title: str
    description: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    deep_link: Optional[str] = None
    space_id: Optional[UUID] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification (internal use)."""
    
    user_id: UUID


class NotificationUpdate(BaseModel):
    """Schema for updating a notification."""
    
    is_read: Optional[bool] = None


class NotificationResponse(NotificationBase):
    """Schema for notification response."""
    
    id: UUID
    user_id: UUID
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
