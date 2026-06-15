"""Crew schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CrewBase(BaseModel):
    """Base crew schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class CrewTableSelection(BaseModel):
    """A specific table a crew is granted access to within a connection."""

    connection_id: UUID
    table_name: str
    schema_name: Optional[str] = None


class CrewConnectionTable(BaseModel):
    """A table granted to a crew within a connection (response shape)."""

    table_name: str
    schema_name: Optional[str] = None


class CrewConnectionResponse(BaseModel):
    """A connection a crew has access to, with its (optional) table narrowing."""

    connection_id: UUID
    name: Optional[str] = None
    connector_id: Optional[str] = None
    # True when the crew has no specific-table rows for this connection (i.e.
    # it inherits every table the space exposes).
    all_tables: bool = True
    tables: List[CrewConnectionTable] = []


class CrewCreate(CrewBase):
    """Crew creation schema."""

    space_id: UUID
    # Connections (a subset of the parent space's connections) this crew may
    # use. Empty/omitted means the crew is created without any explicit
    # connection grant.
    connection_ids: Optional[List[UUID]] = None
    # Optional per-connection table narrowing. A connection present in
    # ``connection_ids`` but absent here keeps access to ALL of the space's
    # tables for it; listing tables narrows the crew to exactly those.
    tables: Optional[List[CrewTableSelection]] = None


class CrewUpdate(BaseModel):
    """Crew update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    space_id: Optional[UUID] = None


class CrewResponse(CrewBase):
    """Crew response schema."""

    id: UUID
    space_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    connection_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class CrewMemberCreate(BaseModel):
    """Crew member creation schema."""

    user_id: UUID
    role: str = Field(..., pattern="^(owner|editor|viewer)$")


class CrewMemberUpdate(BaseModel):
    """Crew member role update schema."""

    role: str = Field(..., pattern="^(owner|editor|viewer)$")


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


class CrewStatusResponse(BaseModel):
    """Crew status response with running tasks info."""

    crew_id: UUID
    has_running_tasks: bool
    running_tasks_count: int
    last_task_started_at: Optional[datetime] = None
    active_task_ids: Optional[list[str]] = None

    model_config = ConfigDict(from_attributes=True)


class CrewMetric(BaseModel):
    """Schema for a metric in the crew overview."""

    value: str
    change: str
    trend: str  # 'up', 'down', 'neutral'


class CrewPIIAccess(BaseModel):
    """Schema for PII access status in the crew overview."""

    status: str  # e.g., 'RESTRICTED', 'OPEN'
    description: str


class CrewActivity(BaseModel):
    """Schema for an activity event in the crew feed."""

    id: str
    user: str
    action: str
    target: str
    time: str
    status: str  # "allow" | "deny"


class CrewStatsResponse(BaseModel):
    """Schema for a crew's statistics."""

    usage_summary: CrewMetric
    insights_contributed: CrewMetric
    pii_access: CrewPIIAccess
    activity_feed: List[CrewActivity] = []

    model_config = ConfigDict(from_attributes=True)
