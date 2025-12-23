"""Dashboard and widget schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardBase(BaseModel):
    """Base dashboard schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class DashboardCreate(DashboardBase):
    """Dashboard creation schema."""

    planet_id: UUID
    template_id: Optional[UUID] = None


class DashboardUpdate(BaseModel):
    """Dashboard update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    canvas_settings: Optional[Dict[str, Any]] = None
    is_locked: Optional[bool] = None


class DashboardResponse(DashboardBase):
    """Dashboard response schema."""

    id: UUID
    planet_id: UUID
    template_id: Optional[UUID] = None
    canvas_settings: Optional[Dict[str, Any]] = None
    is_locked: bool
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WidgetBase(BaseModel):
    """Base widget schema."""

    type: str = Field(..., pattern="^(chart|kpi|table|ai-box|text)$")
    title: str = Field(..., min_length=1, max_length=255)
    position: Dict[str, float] = Field(..., description="Position {x, y}")
    size: Dict[str, float] = Field(..., description="Size {width, height}")


class WidgetCreate(WidgetBase):
    """Widget creation schema."""

    dashboard_id: UUID
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None


class WidgetUpdate(BaseModel):
    """Widget update schema."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None


class WidgetResponse(WidgetBase):
    """Widget response schema."""

    id: UUID
    dashboard_id: UUID
    data: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    connection_id: Optional[UUID] = None
    query_id: Optional[UUID] = None
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

    dashboard_id: UUID


class ConnectionResponse(ConnectionBase):
    """Widget connection response schema."""

    id: UUID
    dashboard_id: UUID
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


class DashboardExportResponse(BaseModel):
    """Dashboard export response schema."""

    dashboard: DashboardResponse
    widgets: List[WidgetResponse]
    connections: List[ConnectionResponse]
    exported_at: str


class DashboardDuplicateRequest(BaseModel):
    """Dashboard duplicate request schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Name for duplicated dashboard (defaults to '{original_name} (Copy)')")
    planet_id: Optional[UUID] = Field(None, description="Planet ID for duplicated dashboard (defaults to original planet)")

