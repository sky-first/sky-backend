"""Notification preference schemas."""

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationPreferenceBase(BaseModel):
    """Base fields shared by create and response."""

    scope_type: Literal["global", "category", "source"]
    scope_value: Optional[str] = None
    channel: Literal["in_app", "email", "push", "all"] = "all"
    enabled: bool = True


class NotificationPreferenceCreate(NotificationPreferenceBase):
    """Schema for creating / upserting a preference. user_id comes from auth."""

    pass


class NotificationPreferenceResponse(NotificationPreferenceBase):
    """Schema for API response."""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceBatchUpdate(BaseModel):
    """Batch update — upsert a list of preferences in one call."""

    preferences: List[NotificationPreferenceCreate]


class PauseRequest(BaseModel):
    """Toggle focus mode (pause all notifications)."""

    paused: bool
