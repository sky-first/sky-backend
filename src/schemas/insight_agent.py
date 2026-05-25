"""Schemas for insight-mode agents.

Insight-mode agents re-run the query that originally produced a widget on
a schedule. They carry:
  - widget_id     — the insight to re-run
  - conversation_id — the chat thread the widget was pinned from (so the
                    agent can append system messages summarising its runs)
  - schedule      — interval value + unit, optional end date
  - identity resolved from the page (user vs SP), see core/agent_identity.py
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


IntervalUnit = Literal["minute", "hour", "day", "week"]


class AgentScheduleConfig(BaseModel):
    """Flexible schedule shape stored as JSONB on the agent."""

    interval_value: int = Field(..., ge=1)
    interval_unit: IntervalUnit
    # Optional hard end date. Null/omitted means the agent runs indefinitely.
    ends_at: Optional[datetime] = None

    # Tag the timezone the client wants runs aligned to; defaults to UTC.
    timezone: str = Field(default="UTC", max_length=50)


class InsightAgentCreate(BaseModel):
    """Payload to turn an insight (widget) into a scheduled agent."""

    widget_id: UUID
    conversation_id: Optional[UUID] = None
    schedule: AgentScheduleConfig
    name: Optional[str] = Field(None, max_length=255)
    notify_on_change: bool = True
    delta_strategy: Literal["hash", "llm"] = "hash"


class InsightAgentUpdate(BaseModel):
    """Partial update. Only schedule-related fields are editable here;
    widget_id / conversation_id are immutable (edit via delete + create)."""

    schedule: Optional[AgentScheduleConfig] = None
    name: Optional[str] = Field(None, max_length=255)
    notify_on_change: Optional[bool] = None
    delta_strategy: Optional[Literal["hash", "llm"]] = None

    @model_validator(mode="after")
    def _at_least_one_field(self):
        values = self.model_dump(exclude_unset=True)
        if not values:
            raise ValueError("at least one field must be provided")
        return self


class InsightAgentResponse(BaseModel):
    id: UUID
    name: str
    status: str                 # active | paused | ended | error
    monitor_type: str           # always 'insight' for this endpoint
    scope: str
    scope_id: str

    widget_id: Optional[UUID]
    conversation_id: Optional[UUID]

    identity_type: str          # user | service_principal
    service_principal_id: Optional[UUID]
    created_by: Optional[UUID]

    schedule_jsonb: Optional[dict]
    ends_at: Optional[datetime]
    delta_strategy: str
    notify_on_change: bool
    consecutive_failures: int

    next_execution_at: Optional[datetime]
    last_execution_at: Optional[datetime]

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentExecutionResponse(BaseModel):
    """One row of `agent_executions` as the Activity tab sees it.

    Includes the Context-Layer evidence trail so the UI can show the
    user *exactly which brain documents* (goals / OKRs / tables /
    widgets …) the agent saw when it produced this run's finding.
    """

    id: UUID
    agent_id: UUID
    status: str                 # queued | running | succeeded | failed | skipped
    cycles_consumed: int
    findings_count: int
    error_message: Optional[str]

    # Delta detection (§8 of master plan)
    delta_kind: Optional[str]   # first_run | none | trivial | material
    delta_summary: Optional[str]

    # Cost / tokens (populated as soon as the AI service reports them)
    llm_tokens_used: Optional[int]
    llm_cost_usd: Optional[float]

    # Context Layer evidence (Phase 2.10)
    context_doc_ids: list[UUID]
    context_intent: Optional[str]

    # Timings
    started_at: datetime
    finished_at: Optional[datetime]
    duration_ms: Optional[int]

    # Agent name + widget info — denormalised so the UI doesn't need N+1 calls.
    agent_name: Optional[str] = None
    widget_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)
