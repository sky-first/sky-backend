"""Notification schemas."""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationBase(BaseModel):
    """Base schema for Notification."""

    type: str = "DASHBOARD_UPDATED"  # Using simple string for now to avoid enum complexity
    title: str
    description: Optional[str] = None
    entity_type: str
    entity_id: str
    deep_link: Optional[str] = None

    title_key: Optional[str] = None
    title_params: Optional[Dict[str, Any]] = None
    description_key: Optional[str] = None
    description_params: Optional[Dict[str, Any]] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a Notification."""

    user_id: UUID
    #: Só para o push — NÃO é gravado (``exclude``). Ids que a app precisa
    #: para abrir o sítio certo ao tocar (``finding_id``, ``agent_id``,
    #: ``conversation_id``…). Ver ``services/push_dispatcher.py``.
    push_data: Optional[Dict[str, Any]] = Field(default=None, exclude=True)


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
