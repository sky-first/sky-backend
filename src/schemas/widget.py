"""Widget and widget-connection schemas.

Renamed from ``schemas/dashboard.py`` in 2026-05-20. The old
``Dashboard*`` schemas were dropped — every dashboard operation is
now a page operation (see ``schemas/page.py``).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.page import PageResponse


class WidgetBase(BaseModel):
    """Base widget schema."""

    type: str = Field(..., pattern="^(chart|kpi|table|ai-box|text|insight|infographic|shape)$")
    title: str = Field(..., min_length=1, max_length=255)
    position: Dict[str, float] = Field(..., description="Position {x, y}")
    size: Dict[str, float] = Field(..., description="Size {width, height}")


_WIDGET_SOURCE_PATTERN = "^(manual|ai_synthesis|mock_fallback|agent)$"


class WidgetCreate(WidgetBase):
    """Widget creation schema."""

    page_id: UUID
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None
    z_index: Optional[int] = None
    # Provenance: who/what stamped this widget. Default 'manual' so old
    # FE clients that don't pass the field still produce auditable rows.
    source: Optional[str] = Field(
        default=None, pattern=_WIDGET_SOURCE_PATTERN
    )


class WidgetUpdate(BaseModel):
    """Widget update schema."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None
    z_index: Optional[int] = None


class WidgetResponse(WidgetBase):
    """Widget response schema."""

    id: UUID
    page_id: UUID
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None
    z_index: int = 0
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConnectionBase(BaseModel):
    """Base widget connection schema."""

    from_widget_id: UUID
    to_widget_id: UUID
    from_anchor: str = Field(..., pattern="^(top|right|bottom|left)$")
    to_anchor: str = Field(..., pattern="^(top|right|bottom|left)$")


class ConnectionCreate(ConnectionBase):
    """Widget connection creation schema."""

    page_id: UUID


class ConnectionResponse(ConnectionBase):
    """Widget connection response schema."""

    id: UUID
    page_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WidgetDataResponse(BaseModel):
    """Widget data response schema."""

    data: Dict[str, Any]
    last_updated: Optional[str] = None


class WidgetExportResponse(BaseModel):
    """Widget export response schema."""

    id: str
    type: str
    title: str
    position: Dict[str, float]
    size: Dict[str, float]
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[str] = None
    query_id: Optional[str] = None
    exported_at: str


class PageExportResponse(BaseModel):
    """Page export response schema — full canvas + widgets + connections."""

    page: PageResponse
    widgets: List[WidgetResponse]
    connections: List[ConnectionResponse]
    exported_at: str


class WidgetFeedbackCreate(BaseModel):
    """Widget feedback creation schema."""

    score: int = Field(..., description="1 for like, -1 for dislike")
    reason: Optional[str] = None
    context: Optional[str] = None


class WidgetFeedbackResponse(BaseModel):
    """Widget feedback response schema."""

    id: UUID
    widget_id: UUID
    user_id: UUID
    score: int
    reason: Optional[str] = None
    context: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
