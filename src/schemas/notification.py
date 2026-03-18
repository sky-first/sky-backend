"""Notification schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    """Base schema for Notification."""

    type: str = "DASHBOARD_UPDATED"  # Using simple string for now to avoid enum complexity
    title: str
    description: Optional[str] = None
    entity_type: str
    entity_id: str
    deep_link: Optional[str] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a Notification."""

    user_id: UUID


class NotificationUpdate(BaseModel):
    """Schema for updating a Notification."""

    is_read: Optional[bool] = None
    read_at: Optional[datetime] = None


class NotificationResponse(NotificationBase):
    """Schema for Notification response."""

    id: UUID
    user_id: UUID
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationCount(BaseModel):
    """Schema for notification counts."""

    count: int
