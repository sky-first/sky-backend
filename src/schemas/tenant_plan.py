"""Pydantic schemas for the tenant plan endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


PlanTierLiteral = Literal["demo", "free", "starter", "pro", "enterprise"]


class TenantPlanResponse(BaseModel):
    """Current tenant plan as visible to any authenticated user.

    Read-side fields only. The CheckConstraint on the table guarantees
    plan_tier is one of the 5 known values, so callers can switch on it
    without a default branch.
    """

    plan_tier: PlanTierLiteral
    updated_at: datetime
    updated_by_user_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TenantPlanUpdate(BaseModel):
    """Owner-only patch payload."""

    plan_tier: PlanTierLiteral
