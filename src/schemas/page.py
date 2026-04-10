"""Page schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.user import UserResponse


class PageBase(BaseModel):
    """Base page schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    type: str = Field(..., pattern="^(personal|team)$")
    color: str = Field(..., pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class PageCreate(PageBase):
    """Page creation schema."""

    crew_id: Optional[UUID] = Field(
        None,
        description="Set to a crew UUID for collaborative pages visible to all "
        "crew members. Leave null/omit for personal pages (owner-only).",
    )


class PageUpdate(BaseModel):
    """Page update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(personal|team)$")
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class PageResponse(PageBase):
    """Page response schema."""

    id: UUID
    owner_id: UUID
    crew_id: Optional[UUID] = None
    is_active: bool
    last_accessed: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageMemberBase(BaseModel):
    """Base page member schema."""

    role: str = Field(..., pattern="^(owner|admin|member|viewer)$")


class PageMemberCreate(PageMemberBase):
    """Page member creation schema."""

    user_id: UUID


class PageMemberResponse(PageMemberBase):
    """Page member response schema."""

    id: UUID
    page_id: UUID
    user_id: UUID
    user: Optional[UserResponse] = None
    joined_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageSwitchRequest(BaseModel):
    """Page switch request schema."""

    page_id: UUID


class PageMemberRoleUpdate(BaseModel):
    """Page member role update schema."""

    role: str = Field(..., pattern="^(admin|member|viewer)$")
