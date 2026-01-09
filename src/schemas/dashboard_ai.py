"""Dashboard AI generation schemas (Davinci)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardAIPlanWidget(BaseModel):
    widget_key: str = Field(..., description="Stable key within the plan (e.g., w1, w2).")
    type: str = Field(..., pattern="^(chart|kpi|table|text)$")
    title: str
    question: str
    viz: Optional[Dict[str, Any]] = None


class DashboardAIPlanRequest(BaseModel):
    """Generate a dashboard plan (no execution)."""

    # Optional overrides. In Personal mode, backend can infer these.
    space_id: Optional[str] = None
    connection_id: Optional[str] = None

    goal: str = Field(default="Billing overview", min_length=1, max_length=200)
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    # Temporary hard cap for auto dashboard creation.
    max_widgets: int = Field(default=8, ge=1, le=8)


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

    goal: str = Field(default="Billing overview", min_length=1, max_length=200)
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    # Temporary hard cap for auto dashboard creation.
    max_widgets: int = Field(default=8, ge=1, le=8)


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

    goal: str = Field(default="Billing overview", min_length=1, max_length=200)
    language: str = Field(default="en", pattern="^(en|pt|es)$")
    max_widgets: int = Field(default=8, ge=1, le=8)


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
