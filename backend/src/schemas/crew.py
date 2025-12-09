"""Crew schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CrewBase(BaseModel):
    """Base crew schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class CrewCreate(CrewBase):
    """Crew creation schema."""

    space_id: UUID


class CrewUpdate(BaseModel):
    """Crew update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class CrewResponse(CrewBase):
    """Crew response schema."""

    id: UUID
    space_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrewMemberCreate(BaseModel):
    """Crew member creation schema."""

    user_id: UUID
    role: str = Field(..., pattern="^(commander|navigator|explorer|guest)$")


class CrewMemberUpdate(BaseModel):
    """Crew member role update schema."""

    role: str = Field(..., pattern="^(commander|navigator|explorer|guest)$")


class CrewMemberResponse(BaseModel):
    """Crew member response schema."""

    id: UUID
    crew_id: UUID
    user_id: UUID
    role: str
    user: Optional[dict] = None
    joined_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

