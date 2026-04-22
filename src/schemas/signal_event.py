from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.signal_event import SignalCategory, SignalConfidence, SignalNature


class SignalEventBase(BaseModel):
    category: SignalCategory
    sub_type: str = Field(..., max_length=100)
    nature: SignalNature
    description: str
    start_date: datetime
    impact_date: Optional[datetime] = None
    confidence: SignalConfidence
    relations: Optional[Dict[str, Any]] = None
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None


class SignalEventCreate(BaseModel):
    # Only content fields — scope (space_id / crew_id / owner_user_id) is
    # assigned by the service based on is_personal / query params.
    category: SignalCategory
    sub_type: str = Field(..., max_length=100)
    nature: SignalNature
    description: str
    start_date: datetime
    impact_date: Optional[datetime] = None
    confidence: SignalConfidence
    relations: Optional[Dict[str, Any]] = None


class SignalEventUpdate(BaseModel):
    category: Optional[SignalCategory] = None
    sub_type: Optional[str] = Field(None, max_length=100)
    nature: Optional[SignalNature] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    impact_date: Optional[datetime] = None
    confidence: Optional[SignalConfidence] = None
    relations: Optional[Dict[str, Any]] = None


class SignalEventResponse(SignalEventBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
