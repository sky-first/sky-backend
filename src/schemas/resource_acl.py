"""Schemas for the resource_acl Share endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ResourceType = Literal[
    "connection", "dashboard", "agent", "knowledge_file", "space", "widget", "page"
]
PrincipalType = Literal["user", "space", "tenant"]
GrantLevel = Literal["viewer", "editor", "owner"]


class GrantCreate(BaseModel):
    """Request body for `POST /resources/{type}/{id}/share`."""

    principal_type: PrincipalType
    # Required for principal_type ∈ {user, space}, omitted (None) when
    # principal_type == "tenant".
    principal_id: Optional[UUID] = None
    level: GrantLevel = Field(default="viewer")


class GrantResponse(BaseModel):
    id: UUID
    resource_type: ResourceType
    resource_id: UUID
    principal_type: PrincipalType
    principal_id: Optional[UUID] = None
    level: GrantLevel
    granted_by: Optional[UUID] = None
    granted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GrantList(BaseModel):
    items: List[GrantResponse]
    total: int
