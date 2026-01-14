"""Template schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TemplateBase(BaseModel):
    """Base template schema."""

    name: str = Field(..., min_length=1, max_length=255)
    creator: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    question: Optional[str] = None
    widgets: List[Dict[str, Any]] = Field(default_factory=list)
    icon: Optional[str] = None
    color: str = Field(..., pattern="^#[0-9A-Fa-f]{6}$")
    popular: bool = False
    enterprise: bool = False


class TemplateCreate(TemplateBase):
    """Template creation schema."""


class TemplateUpdate(BaseModel):
    """Template update schema."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    creator: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    question: Optional[str] = None
    widgets: Optional[List[Dict[str, Any]]] = None
    icon: Optional[str] = None
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    popular: Optional[bool] = None
    enterprise: Optional[bool] = None


class TemplateResponse(TemplateBase):
    """Template response schema."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TemplateApplyRequest(BaseModel):
    """Template apply request schema."""

    dashboard_id: UUID
    position: Optional[Dict[str, float]] = Field(None, description="Optional position {x, y}")


class TemplateApplyResponse(BaseModel):
    """Template apply response schema."""

    widgets: List[Dict[str, Any]] = Field(description="Created widgets")
