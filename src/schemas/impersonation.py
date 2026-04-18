"""Impersonation request / response schemas (ADR-001 Fase 1)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ImpersonationStartRequest(BaseModel):
    """Body for POST /users/{user_id}/impersonate."""

    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Why this impersonation is happening. Audit-logged. Must be non-trivial.",
    )
    max_minutes: int = Field(
        30,
        ge=1,
        le=60,
        description="Session duration. Hard-capped at 60 minutes by ADR-001.",
    )
    mode: Literal["read_only", "read_write"] = Field(
        "read_only",
        description="Default read_only; read_write requires explicit opt-in (audit-flagged).",
    )


class ImpersonationSessionResponse(BaseModel):
    """Response from POST /users/{user_id}/impersonate."""

    session_token: str
    on_behalf_of: str
    expires_at: datetime
    mode: Literal["read_only", "read_write"]


class ImpersonationExitResponse(BaseModel):
    """Response from POST /users/me/impersonate/exit."""

    message: str = "Impersonation session ended"
    ended_at: Optional[datetime] = None
