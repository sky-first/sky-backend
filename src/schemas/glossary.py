from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GlossaryTermBase(BaseModel):
    term: str = Field(..., min_length=1, max_length=255)
    definition: str = Field(..., min_length=1)
    notes: Optional[str] = None


class GlossaryTermCreate(GlossaryTermBase):
    pass


class GlossaryTermUpdate(BaseModel):
    term: Optional[str] = Field(None, min_length=1, max_length=255)
    definition: Optional[str] = Field(None, min_length=1)
    notes: Optional[str] = None


class GlossaryTermResponse(GlossaryTermBase):
    id: UUID
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
