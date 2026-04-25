"""Pydantic schemas for the Metric model (Knowledge refactor Phase 2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MetricScope = Literal["personal", "crew", "space", "org"]
MetricStatus = Literal["draft", "active", "deprecated"]
MetricLanguage = Literal["sql", "describe"]


class MetricBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None

    scope: MetricScope
    # Required for personal/crew/space; null for org. Service layer
    # cross-checks this against the requesting user's identity.
    scope_id: Optional[UUID] = None

    status: MetricStatus = "draft"

    formula_text: Optional[str] = None
    formula_description: Optional[str] = None
    formula_language: MetricLanguage = "sql"

    source_id: Optional[UUID] = None
    source_table: Optional[str] = None
    source_column: Optional[str] = None

    aggregation: Optional[str] = None
    unit: Optional[str] = None
    time_grain: Optional[str] = None

    target_value: Optional[Decimal] = None
    target_date: Optional[date] = None
    threshold_warning: Optional[Decimal] = None
    threshold_critical: Optional[Decimal] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _strip_blank_tags(cls, v: List[str]) -> List[str]:
        return [t.strip() for t in v if t and t.strip()]


class MetricCreate(MetricBase):
    """Body of `POST /api/v1/metrics`. Slug is derived from `name`."""

    pass


class MetricUpdate(BaseModel):
    """All fields optional — the service applies a partial update."""

    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    status: Optional[MetricStatus] = None
    formula_text: Optional[str] = None
    formula_description: Optional[str] = None
    formula_language: Optional[MetricLanguage] = None
    source_id: Optional[UUID] = None
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    aggregation: Optional[str] = None
    unit: Optional[str] = None
    time_grain: Optional[str] = None
    target_value: Optional[Decimal] = None
    target_date: Optional[date] = None
    threshold_warning: Optional[Decimal] = None
    threshold_critical: Optional[Decimal] = None
    tags: Optional[List[str]] = None


class MetricRead(MetricBase):
    """Outbound shape — adds server-set fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str

    owner_user_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    updated_by_user_id: Optional[UUID] = None
    certified_by_user_id: Optional[UUID] = None
    certified_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime
