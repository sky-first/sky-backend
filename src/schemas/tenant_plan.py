"""Pydantic schemas for the tenant plan endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


PlanTierLiteral = Literal["demo", "free", "starter", "pro", "enterprise"]

# Enforced commercial tier — distinct from the legacy product tiers
# above. The Pricing Fase 2 customer-facing /usage endpoint speaks this
# vocabulary because it mirrors what tenant_plan_limits.tier stores.
PricingTierLiteral = Literal["starter", "foundation", "scale", "enterprise"]


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


class UsagePercent(BaseModel):
    """Per-resource usage % — null when the ceiling is unlimited."""

    agents: Optional[float] = None
    users: Optional[float] = None
    storage: Optional[float] = None
    queries: Optional[float] = None


class TenantUsageResponse(BaseModel):
    """Customer-facing usage snapshot for the topbar pill + slot hints.

    Mirrors the Console ``/tenants/{slug}/usage`` payload but scoped to
    the caller's own tenant and shaped exactly the way the FE
    `pricing-store` expects (flat counters + a `usage_percent` map with
    `null` for unlimited resources). The Console flavour returns 0.0
    for unlimited — we coerce to ``None`` here so the FE can render
    "—" without sniffing the limit.
    """

    tier: PricingTierLiteral
    max_agents: Optional[int] = None
    current_agents: int
    max_users: Optional[int] = None
    current_users: int
    max_storage_gb: Optional[int] = None
    current_storage_bytes: int
    max_queries_per_month: Optional[int] = None
    current_queries_this_month: int
    usage_percent: UsagePercent
    queries_period_start: datetime
    updated_at: datetime


class UsageAlertRequest(BaseModel):
    """Fase 2 placeholder for the email-on-threshold flow.

    The real email (and Stripe paywall) is Fase 4; for now we just log
    intent into the Console audit log so we can later replay it and
    confirm the FE fires at the right moments.
    """

    resource: Literal["agents", "users", "storage", "queries"]
    threshold: int = Field(ge=0, le=100)
    current_percent: float = Field(ge=0.0)


class UsageAlertResponse(BaseModel):
    accepted: bool
    audit_id: Optional[str] = None
