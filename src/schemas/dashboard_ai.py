"""Dashboard AI generation schemas (Davinci)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DashboardAIPlanWidget(BaseModel):
    widget_key: str = Field(
        ..., description="Stable key within the plan (e.g., w1, w2)."
    )
    type: str = Field(..., pattern="^(chart|kpi|table|text|infographic)$")
    title: str
    question: str
    viz: Optional[Dict[str, Any]] = None


class DashboardAIPlanRequest(BaseModel):
    """Generate a dashboard plan (no execution)."""

    # Optional overrides. In Personal mode, backend can infer these.
    space_id: Optional[str] = None
    connection_id: Optional[str] = None

    # NOTE: prefer original_question over goal. We keep goal for backward-compat.
    goal: Optional[str] = Field(default=None, min_length=1, max_length=200)
    original_question: Optional[str] = Field(
        default=None, min_length=1, max_length=4000
    )
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    # Temporary hard cap for auto dashboard creation.
    max_widgets: int = Field(default=8, ge=1, le=8)

    # Optional conversation context (for more relevant planning)
    initial_ai_response: Optional[str] = None
    context_spaces: Optional[List[str]] = None
    context_crews: Optional[List[str]] = None
    context_tables: Optional[List[str]] = None

    @model_validator(mode="after")
    def _normalize_goal(self) -> "DashboardAIPlanRequest":
        # Frontend now sends `original_question`; older clients send `goal`.
        oq = (
            (self.original_question or "").strip()
            if isinstance(self.original_question, str)
            else ""
        )
        g = (self.goal or "").strip() if isinstance(self.goal, str) else ""
        if not oq and not g:
            raise ValueError("Either 'original_question' or 'goal' must be provided.")
        # Always use the original_question as the primary planning 'goal'
        self.goal = oq or g
        return self


class DashboardAIPlanResponse(BaseModel):
    dashboard_name: str
    description: Optional[str] = None
    widgets: List[DashboardAIPlanWidget]
    meta: Optional[Dict[str, Any]] = None


class DashboardAIBuildRequest(BaseModel):
    """Build a dashboard from a plan (executes queries, creates widgets)."""

    # Optional overrides. In Personal mode, backend can infer these.
    space_id: Optional[str] = None
    connection_id: Optional[str] = None

    # Either provide a plan (from /ai/plan) or let backend generate one from goal.
    plan: Optional[DashboardAIPlanResponse] = None

    goal: Optional[str] = Field(default=None, min_length=1, max_length=200)
    original_question: Optional[str] = Field(
        default=None, min_length=1, max_length=4000
    )
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    # Temporary hard cap for auto dashboard creation.
    max_widgets: int = Field(default=8, ge=1, le=8)

    # Optional conversation context (forwarded to planning step when plan is generated server-side)
    initial_ai_response: Optional[str] = None
    context_spaces: Optional[List[str]] = None
    context_crews: Optional[List[str]] = None
    context_tables: Optional[List[str]] = None

    @model_validator(mode="after")
    def _normalize_goal(self) -> "DashboardAIBuildRequest":
        oq = (
            (self.original_question or "").strip()
            if isinstance(self.original_question, str)
            else ""
        )
        g = (self.goal or "").strip() if isinstance(self.goal, str) else ""
        if not oq and not g and self.plan is None:
            # If a plan was provided, goal/original_question is not strictly required.
            raise ValueError(
                "Either 'original_question' or 'goal' must be provided when plan is not set."
            )
        self.goal = oq or g or self.goal
        return self


class DashboardAIBuildWidgetResult(BaseModel):
    widget_id: UUID
    query_id: Optional[UUID] = None
    widget_key: Optional[str] = None


class DashboardAIBuildResponse(BaseModel):
    dashboard_id: UUID
    widgets: List[DashboardAIBuildWidgetResult]
    meta: Optional[Dict[str, Any]] = None


# ==========================
# Async dashboard build (background)
# ==========================


class DashboardAIBuildAsyncRequest(BaseModel):
    """Enqueue an async dashboard build job."""

    # Optional overrides. In Personal mode, backend can infer these.
    space_id: Optional[str] = None
    connection_id: Optional[str] = None

    goal: Optional[str] = Field(default=None, min_length=1, max_length=200)
    original_question: Optional[str] = Field(
        default=None, min_length=1, max_length=4000
    )
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    max_widgets: int = Field(default=8, ge=1, le=8)

    # Optional pre-calculated plan (from chat/frontend). If provided, the worker
    # will use it directly instead of calling the AI service for re-planning.
    plan: Optional[Dict[str, Any]] = None

    # Optional conversation context (stored in job.plan["_context"] for worker usage)
    initial_ai_response: Optional[str] = None
    context_spaces: Optional[List[str]] = None
    context_crews: Optional[List[str]] = None
    context_tables: Optional[List[str]] = None

    @model_validator(mode="after")
    def _normalize_goal(self) -> "DashboardAIBuildAsyncRequest":
        oq = (
            (self.original_question or "").strip()
            if isinstance(self.original_question, str)
            else ""
        )
        g = (self.goal or "").strip() if isinstance(self.goal, str) else ""
        if not oq and not g and self.plan is None:
            raise ValueError(
                "Either 'original_question', 'goal', or 'plan' must be provided."
            )
        self.goal = oq or g or self.goal
        return self


class DashboardAIBuildAsyncResponse(BaseModel):
    job_id: UUID
    status: str
    total_widgets: int
    completed_widgets: int
    dashboard_id: Optional[UUID] = None
    error: Optional[str] = None


class DashboardBuildJobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    total_widgets: int
    completed_widgets: int
    dashboard_id: Optional[UUID] = None
    created_widget_ids: Optional[List[UUID]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
