from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.agent import AgentArchetype, AgentFrequency, AgentScope, AgentStatus, FindingSeverity, FindingType


# Phase 4.2: explicit set of agent monitor types the platform supports.
# Kept as a tuple (not an Enum) because `datasource` is a legacy alias
# for `scan` — Pydantic Enums reject aliases, a validator does not.
# Clients still writing `datasource` keep working; new writers should
# prefer `scan`. `context` is reserved for Phase 5 (full-context mode).
MONITOR_TYPE_VALUES: tuple[str, ...] = (
    "question",
    "sql",
    "scan",
    "datasource",
    "context",
    "insight",
)


def _validate_monitor_type(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s not in MONITOR_TYPE_VALUES:
        raise ValueError(
            f"monitor_type must be one of {MONITOR_TYPE_VALUES}, got {v!r}"
        )
    return s


# ─── Agent schemas ───

class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    archetype: AgentArchetype = AgentArchetype.CUSTOM
    scope: AgentScope = AgentScope.SPACE
    # Optional because the personal-mode wizard does not always have a
    # scope_id at submission time. The service layer normalises personal
    # agents to scope_id == user.id, so accepting None here keeps the
    # invariant without forcing the FE to fabricate a placeholder.
    scope_id: Optional[str] = Field(default=None, max_length=255)
    scope_name: Optional[str] = Field(None, max_length=255)
    monitor_type: str = Field("question", max_length=20)
    focus: Optional[str] = None  # The question or instructions
    custom_sql: Optional[str] = None  # For sql monitor_type
    frequency: AgentFrequency = AgentFrequency.DAILY
    depth: Optional[str] = Field("standard", max_length=20)
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None  # Granular table selection
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    # Transcript from the AI chat when the agent was created via the
    # "Create agent from this chat" CTA. Plain text, nullable.
    chat_context: Optional[str] = None
    # Full Universe-Intelligence scope: dict keyed by entity kind. After
    # the Knowledge refactor (Phase 1) the kinds are: glossary_terms (and
    # metrics in Phase 2), enterprise_relationships, widgets, insights,
    # pages. Empty arrays or missing keys = "no filter for that kind".
    selected_context: Optional[Dict[str, List[str]]] = None
    # Phase 6 — when true the agent runtime drops every connection whose
    # tier ≠ 'internal' before issuing the query. Compliance-bound deploys
    # opt in here so autonomous agents only touch low-risk data sources.
    auditable_only: Optional[bool] = False

    @field_validator("monitor_type")
    @classmethod
    def _check_monitor_type(cls, v):
        return _validate_monitor_type(v) or "question"


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
    chat_context: Optional[str] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    # Flexible schedule — supersedes `frequency` when present.
    # Shape: {interval_value: int, interval_unit: minute|hour|day|week|month,
    #         end: {type: forever|once|n_runs|until_date, value: int|iso?}}
    schedule_jsonb: Optional[Dict[str, Any]] = None
    # Phase 6 — auditable_only toggle. See AgentCreate for semantics.
    auditable_only: Optional[bool] = None

    @field_validator("monitor_type")
    @classmethod
    def _check_monitor_type(cls, v):
        return _validate_monitor_type(v)


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
    rows: Optional[Dict[str, Any]] = None  # {columns, data, truncated?} — consumed by Cockpit
    # Sprint 1.17 round 5 — visualisation hint the Pulse FE uses to
    # pick the card variant + the widget kind on "Add to page".
    viz_kind: Optional[str] = None
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
    chat_context: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    auditable_only: bool = False
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    # Nested — only included when fetching single agent
    findings: Optional[List[AgentFindingResponse]] = None
    # Option B: True when the caller may SEE the agent (management) but its
    # findings/insights were withheld because they are not a crew/space member.
    # Lets the UI render an "ask to be added" mask instead of "no insights".
    findings_restricted: bool = False

    model_config = ConfigDict(from_attributes=True)


class AddFindingToPageRequest(BaseModel):
    """Payload for POST /agents/{agent_id}/findings/{finding_id}/add-to-page.

    The finding is materialised as a Widget on the target page. The
    server picks the widget ``type`` from ``finding.viz_kind`` (see
    `_viz_kind_to_widget_type` in agent_service); the caller optionally
    pins position/size, otherwise defaults are applied.
    """

    page_id: UUID
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None


class AddFindingToPageResponse(BaseModel):
    """Response after materialising a finding on a page — returns the
    new Widget id so the FE can navigate / scroll to it."""

    widget_id: UUID
    page_id: UUID
    finding_id: UUID
    widget_type: str


class AgentListResponse(BaseModel):
    """Lightweight response for list/mutation endpoints — agent metadata only.

    Findings are NOT included here. The list endpoint (``GET /api/v1/agents/``)
    deliberately does not eager-load ``Agent.findings`` to keep DB connection
    pool usage bounded (see commit 46623cf: 62 concurrent list calls each
    doing ``selectinload(findings)`` were exhausting the pool). Because the
    relationship is async-lazy, leaving ``findings`` on this response triggered
    a Pydantic ``get_attribute_error`` (MissingGreenlet) during serialization
    of the un-loaded relationship → 500 to the client.

    Callers that need findings should use ``GET /api/v1/agents/{agent_id}``
    (``AgentResponse``), which goes through ``get_with_findings``.
    """
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
    chat_context: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    auditable_only: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
