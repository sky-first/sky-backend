"""Permission schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PermissionBase(BaseModel):
    """Base permission schema."""

    access_level: str = Field(..., pattern="^(full|read-only|custom)$")
    table_access: Optional[List[str]] = Field(None, description="List of table names (if access_level = 'custom')")


class ConnectionPermissionCreate(PermissionBase):
    """Connection permission creation schema."""

    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None


class PermissionUpdate(BaseModel):
    """Permission update schema."""

    access_level: Optional[str] = Field(None, pattern="^(full|read-only|custom)$")
    table_access: Optional[List[str]] = None


class PermissionResponse(PermissionBase):
    """Permission response schema."""

    id: UUID
    connection_id: UUID
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PermissionValidateRequest(BaseModel):
    """Permission validation request schema."""

    user_id: UUID
    connection_id: UUID
    action: str = Field(..., description="Action to validate (read, write, etc)")


class PermissionValidateResponse(BaseModel):
    """Permission validation response schema."""

    allowed: bool
    reason: Optional[str] = None

