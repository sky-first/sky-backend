"""Planet schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.user import UserResponse


class PlanetBase(BaseModel):
    """Base planet schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    type: str = Field(..., pattern="^(personal|team)$")
    color: str = Field(..., pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class PlanetCreate(PlanetBase):
    """Planet creation schema."""


class PlanetUpdate(BaseModel):
    """Planet update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(personal|team)$")
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class PlanetResponse(PlanetBase):
    """Planet response schema."""

    id: UUID
    owner_id: UUID
    is_active: bool
    last_accessed: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanetMemberBase(BaseModel):
    """Base planet member schema."""

    role: str = Field(..., pattern="^(owner|admin|member|viewer)$")


class PlanetMemberCreate(PlanetMemberBase):
    """Planet member creation schema."""

    user_id: UUID


class PlanetMemberResponse(PlanetMemberBase):
    """Planet member response schema."""

    id: UUID
    planet_id: UUID
    user_id: UUID
    user: Optional[UserResponse] = None
    joined_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanetSwitchRequest(BaseModel):
    """Planet switch request schema."""

    planet_id: UUID


class PlanetMemberRoleUpdate(BaseModel):
    """Planet member role update schema."""

    role: str = Field(..., pattern="^(admin|member|viewer)$")
