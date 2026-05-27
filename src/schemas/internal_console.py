"""Pydantic schemas for the Internal Console API (Projeto B).

Wire format for the ``/api/console/v1/*`` routes. Three groups:

* Audit log — read-only; the Console never POSTs to this surface
  directly. Audit entries are written by the service layer.
* Provisioning jobs — read-only from the client's perspective. POSTing
  to ``/tenants`` or ``/tenants/{slug}/suspend`` creates a job
  implicitly; the client polls the job by id.
* Tenant management — the Console-facing variants of the tenant
  schemas. Reuses :mod:`src.schemas.tenant` for the registry payload
  shape but wraps it with Console-specific extras (subscription dates,
  recent activity, computed capacity utilisation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.internal_console import (
    AuditAction,
    AuditResult,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.schemas.tenant import TenantCreate, TenantRead, TenantUpdate


# ── Audit log ──────────────────────────────────────────────────────


class AuditEntryRead(BaseModel):
    """Single row from ``internal_console_audit``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_email: str
    actor_ip: Optional[str]
    action: AuditAction
    tenant_slug: Optional[str]
    request_payload: Optional[Dict[str, Any]]
    result: AuditResult
    result_details: Optional[Dict[str, Any]]
    timestamp: datetime


class AuditListResponse(BaseModel):
    items: List[AuditEntryRead]
    total: int


# ── Provisioning jobs ──────────────────────────────────────────────


class ProvisioningJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_slug: str
    actor_email: str
    job_type: ProvisioningJobType
    status: ProvisioningJobStatus
    started_at: datetime
    completed_at: Optional[datetime]
    output: Optional[str]
    error_message: Optional[str]
    request_payload: Optional[Dict[str, Any]]


class ProvisioningJobListResponse(BaseModel):
    items: List[ProvisioningJobRead]
    total: int


# ── Tenant management (Console wrappers) ───────────────────────────


class ConsoleTenantSummary(BaseModel):
    """Row shape for the Console's tenants-list table.

    Computed fields (``capacity_pct_*``) come from the service layer
    by combining ``tenant_registry.capacity_used`` with
    ``capacity_limits``. The frontend renders progress bars without
    re-computing.
    """

    model_config = ConfigDict(from_attributes=True)

    slug: str
    display_name: str
    tier: str
    is_active: bool
    suspended_at: Optional[datetime]
    custom_domain: Optional[str]
    created_at: datetime
    # ── computed by the service layer ──
    capacity_pct_agents: float = 0.0
    capacity_pct_sources: float = 0.0
    capacity_pct_indexed_gb: float = 0.0


class ConsoleTenantList(BaseModel):
    items: List[ConsoleTenantSummary]
    total: int


class ConsoleTenantDetail(TenantRead):
    """Tenant detail screen payload. Extends the registry shape with
    operational extras the Console renders on the Overview tab."""

    # Last 50 audit entries scoped to this tenant. Filled by the
    # service layer; the API never asks the client to provide it.
    recent_audit: List[AuditEntryRead] = Field(default_factory=list)
    # Last 10 provisioning jobs against this tenant.
    recent_jobs: List[ProvisioningJobRead] = Field(default_factory=list)


# ── Action payloads ────────────────────────────────────────────────


class CreateTenantRequest(TenantCreate):
    """Console-facing create payload.

    Adds an ``admin_email`` so the create handler can seed a real
    admin user in the freshly-provisioned tenant DB. Optional — if
    omitted the tenant is created with no admin and someone has to
    bootstrap one manually later.
    """

    admin_email: Optional[str] = Field(
        None,
        description=(
            "If set, the create job also seeds a first admin user in "
            "the tenant DB with this email."
        ),
        max_length=255,
    )


class UpdateTenantRequest(TenantUpdate):
    """Console-facing update payload — passes straight through to the
    underlying tenant schema. Wrapper exists so future Console-only
    fields (e.g. CSM notes) can land here without touching the
    registry schema."""

    pass


class SuspendTenantRequest(BaseModel):
    """Optional reason payload for the suspend action."""

    reason: Optional[str] = Field(None, max_length=500)


class DestroyTenantRequest(BaseModel):
    """Confirmation token + double-typed slug — destruction is
    irreversible so the API requires the caller to type the slug
    twice and acknowledge."""

    confirmation_slug: str = Field(..., max_length=50)
    confirmation_phrase: str = Field(
        ..., description="Must be exactly 'I understand this is irreversible'"
    )


# ── Dashboard ──────────────────────────────────────────────────────


class DashboardSummary(BaseModel):
    """Aggregate stats for ``/api/console/v1/dashboard``."""

    total_tenants: int
    active_tenants: int
    suspended_tenants: int
    tenants_by_tier: Dict[str, int]
    recent_audit: List[AuditEntryRead] = Field(default_factory=list)


# ── Me ─────────────────────────────────────────────────────────────


class ConsoleMeResponse(BaseModel):
    """``GET /api/console/v1/me`` — what the Console knows about the
    currently-authenticated Sky-team member."""

    email: str
    role: str  # admin | operator | read_only
    is_sky_team: bool
