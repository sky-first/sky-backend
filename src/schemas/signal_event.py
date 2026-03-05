from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from src.models.signal_event import SignalCategory, SignalNature, SignalConfidence


class SignalEventBase(BaseModel):
    category: SignalCategory
    sub_type: str = Field(..., max_length=100)
    nature: SignalNature
    description: str
    start_date: datetime
    impact_date: Optional[datetime] = None
    confidence: SignalConfidence
    relations: Optional[Dict[str, Any]] = None


class SignalEventCreate(SignalEventBase):
    pass


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
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
