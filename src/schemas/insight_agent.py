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
