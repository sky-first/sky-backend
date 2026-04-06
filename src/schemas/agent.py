from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.agent import AgentArchetype, AgentFrequency, AgentScope, AgentStatus, FindingSeverity, FindingType


# ─── Agent schemas ───

class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    archetype: AgentArchetype = AgentArchetype.CUSTOM
    scope: AgentScope = AgentScope.SPACE
    scope_id: str = Field(..., max_length=255)
    scope_name: Optional[str] = Field(None, max_length=255)
    monitor_type: str = Field("question", max_length=20)  # question, datasource, sql
    focus: Optional[str] = None  # The question or instructions
    custom_sql: Optional[str] = None  # For sql monitor_type
    frequency: AgentFrequency = AgentFrequency.DAILY
    depth: Optional[str] = Field("standard", max_length=20)
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None  # Granular table selection
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    monitor_type: Optional[str] = Field(None, max_length=20)
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    frequency: Optional[AgentFrequency] = None
    depth: Optional[str] = Field(None, max_length=20)
    table_ids: Optional[List[str]] = None
    connection_ids: Optional[List[UUID]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None


class AgentFindingResponse(BaseModel):
    id: UUID
    agent_id: UUID
    type: FindingType
    severity: FindingSeverity
    title: str
    description: str
    confidence: Optional[float] = None
    query: Optional[str] = None
    evidence: Optional[str] = None
    reasoning: Optional[str] = None
    recommendation: Optional[str] = None
    data_sources: Optional[List[Optional[str]]] = None
    connection_id: Optional[UUID] = None
    connection_name: Optional[str] = None
    dismissed: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentExecutionResponse(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    cycles_consumed: int
    findings_count: int
    error_message: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AgentResponse(BaseModel):
    id: UUID
    name: str
    archetype: str
    scope: str
    scope_id: str
    scope_name: Optional[str] = None
    status: str
    monitor_type: str = "question"
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    # Nested — only included when fetching single agent
    findings: Optional[List[AgentFindingResponse]] = None

    model_config = ConfigDict(from_attributes=True)


class AgentListResponse(BaseModel):
    """Lightweight response — all fields except findings."""
    id: UUID
    name: str
    archetype: str
    scope: str
    scope_id: str
    scope_name: Optional[str] = None
    status: str
    monitor_type: str = "question"
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
