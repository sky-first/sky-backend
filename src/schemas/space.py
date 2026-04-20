"""Space schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.user import UserResponse


class SpaceBase(BaseModel):
    """Base space schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None)  # Allow any string or None, validate in service if needed
    icon: Optional[str] = None
    privacy: str = Field("private", description="public, private")  # Default can be 'private'
    sensitivity: str = Field("internal", description="internal, confidential, restricted")

    @field_validator("color", mode="before")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        """Validate and normalize color value."""
        if v is None or v == "":
            return None
        # If it's already a valid hex color, return as is
        if isinstance(v, str) and v.startswith("#") and len(v) == 7:
            try:
                int(v[1:], 16)  # Validate hex
                return v
            except ValueError:
                pass
        # If it's a color name or invalid format, return None
        return None


class SpaceCreate(SpaceBase):
    """Space creation schema."""


class SpaceUpdate(BaseModel):
    """Space update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None)  # Allow any string or None, validate in service if needed
    icon: Optional[str] = None
    privacy: Optional[str] = Field(None, pattern="^(public|private)$")
    sensitivity: Optional[str] = Field(None, pattern="^(internal|confidential|restricted)$")


class SpaceResponse(SpaceBase):
    """Space response schema."""

    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    connection_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class SpaceMemberCreate(BaseModel):
    """Space member creation schema."""

    user_id: UUID


class SpaceMemberResponse(BaseModel):
    """Space member response schema."""

    id: UUID
    space_id: UUID
    user_id: UUID
    user: Optional[UserResponse] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpaceTableCreate(BaseModel):
    """Space table creation schema."""

    connection_id: UUID
    table_name: str
    schema_name: Optional[str] = None


class SpaceTableResponse(BaseModel):
    """Space table response schema."""

    id: UUID
    space_id: UUID
    connection_id: UUID
    table_name: str
    schema_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpaceMetric(BaseModel):
    """Schema for a metric in the space overview."""

    value: str
    change: str
    trend: str  # 'up', 'down', 'neutral'


class SpaceActivity(BaseModel):
    """Schema for an activity in the space feed."""

    id: UUID
    user: str
    action: str
    target: str
    time: str


class SpaceStatsResponse(BaseModel):
    """Schema for a space's statistics."""

    total_queries: SpaceMetric
    active_users: SpaceMetric
    data_usage: SpaceMetric
    compliance_score: SpaceMetric
    activity_feed: List[SpaceActivity]

    model_config = ConfigDict(from_attributes=True)
