"""Ticket request / response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
#  Requests
# ---------------------------------------------------------------------------


class TicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="", max_length=16_000)
    category: str = Field(default="other")
    severity: str = Field(default="medium")
    space_id: Optional[UUID] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class TicketUpdateRequest(BaseModel):
    """Admin-only patch — status / severity / assigned / external_ref."""

    status: Optional[str] = None
    severity: Optional[str] = None
    assigned_to_user_id: Optional[UUID] = None
    external_ref: Optional[str] = Field(default=None, max_length=64)


class TicketCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=16_000)


class TicketEscalateRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2_000)


# ---------------------------------------------------------------------------
#  Responses
# ---------------------------------------------------------------------------


class TicketEventResponse(BaseModel):
    id: UUID
    actor_user_id: Optional[UUID]
    kind: str
    payload: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketResponse(BaseModel):
    id: UUID
    reporter_user_id: Optional[UUID]
    space_id: Optional[UUID]
    subject: str
    body: str
    category: str
    severity: str
    status: str
    assigned_to_user_id: Optional[UUID]
    escalated_at: Optional[datetime]
    escalated_by_user_id: Optional[UUID]
    external_ref: Optional[str]
    context: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketDetailResponse(TicketResponse):
    events: List[TicketEventResponse] = Field(default_factory=list)


class TicketListResponse(BaseModel):
    items: List[TicketResponse]
    total: int
