"""Workspace schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.schemas.user import UserResponse


class WorkspaceBase(BaseModel):
    """Base workspace schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    type: str = Field(..., pattern="^(personal|team)$")
    color: str = Field(..., pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class WorkspaceCreate(WorkspaceBase):
    """Workspace creation schema."""


class WorkspaceUpdate(BaseModel):
    """Workspace update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None


class WorkspaceResponse(WorkspaceBase):
    """Workspace response schema."""

    id: UUID
    owner_id: UUID
    is_active: bool
    last_accessed: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkspaceMemberBase(BaseModel):
    """Base workspace member schema."""

    role: str = Field(..., pattern="^(owner|admin|member|viewer)$")


class WorkspaceMemberCreate(WorkspaceMemberBase):
    """Workspace member creation schema."""

    user_id: UUID


class WorkspaceMemberResponse(WorkspaceMemberBase):
    """Workspace member response schema."""

    id: UUID
    workspace_id: UUID
    user_id: UUID
    user: Optional[UserResponse] = None
    joined_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspaceSwitchRequest(BaseModel):
    """Workspace switch request schema."""

    workspace_id: UUID


class WorkspaceMemberRoleUpdate(BaseModel):
    """Workspace member role update schema."""

    role: str = Field(..., pattern="^(admin|member|viewer)$")
