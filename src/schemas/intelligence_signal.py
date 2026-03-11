
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class IntelligenceSignalBase(BaseModel):
    category: str = Field(..., description="now, smart, or explore")
    title: str = Field(..., max_length=255)
    content: str
    impact: Optional[str] = None
    reason: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    cta_label: Optional[str] = None
    cta_action: Optional[str] = None
    cta_params: Optional[Dict[str, Any]] = None
    chart_data: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = 1.0
    space_id: Optional[str] = None

class IntelligenceSignalCreate(IntelligenceSignalBase):
    planet_id: UUID

class IntelligenceSignalUpdate(BaseModel):
    is_dismissed: Optional[datetime] = None
    # Add other fields if manual editing is needed later
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None

class IntelligenceSignalResponse(IntelligenceSignalBase):
    id: UUID
    planet_id: UUID
    is_dismissed: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
