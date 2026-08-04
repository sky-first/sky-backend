"""Pydantic schemas for the tenant registry.

These schemas are the contract for the Internal Console (PR sequence
``03-internal-console-spec-v2.md``). The runtime tenant resolver
middleware (PR #2) reads ``Tenant`` rows directly through the ORM and
does not depend on these schemas.

``slug`` is the only field with a regex check at the API boundary:
the resolver later embeds it in hostnames (``workspace-<slug>.…``)
and AWS Secrets Manager paths (``sky/clients/<slug>/…``), so anything
permissive here turns into an injection surface there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.tenant import (
    AUTH_METHOD_KEYS,
    DEFAULT_AUTH_METHODS,
    DEFAULT_CAPACITY_SHAPE,
    TenantTier,
)


# ``^[a-z0-9-]{2,50}$`` — same shape enforced by the Postgres CHECK
# constraint in the migration. Pydantic enforces it at the boundary so
# we never round-trip an invalid slug to the database.
_SLUG_PATTERN = r"^[a-z0-9-]{2,50}$"


class CapacityDimensions(BaseModel):
    """Capacity counters for the three pricing dimensions.

    Always shipped as a complete shape — missing keys are filled with 0
    so downstream code can assume the three values always exist.
    """

    agents: int = Field(0, ge=0)
    sources: int = Field(0, ge=0)
    indexed_gb: int = Field(0, ge=0)


class AuthMethods(BaseModel):
    """Per-tenant authentication methods.

    Drives what the ``/login`` page renders and which auth endpoints the
    backend accepts for this tenant. At least one method must be enabled
    — a tenant with all four false would have no way to sign in.
    """

    password: bool = False
    google: bool = False
    azure: bool = False
    okta: bool = False

    @model_validator(mode="after")
    def _at_least_one_enabled(self) -> "AuthMethods":
        if not any(getattr(self, k) for k in AUTH_METHOD_KEYS):
            raise ValueError(
                "At least one authentication method must be enabled"
            )
        return self


class TenantBase(BaseModel):
    """Fields shared by create/update/read."""

    slug: str = Field(..., min_length=2, max_length=50, pattern=_SLUG_PATTERN)
    display_name: str = Field(..., min_length=1, max_length=255)
    tier: TenantTier
    db_host: str = Field(..., max_length=255)
    db_port: int = Field(5432, ge=1, le=65535)
    db_name: str = Field(..., max_length=63)
    db_credentials_secret_arn: str = Field(..., max_length=512)
    redis_host: str = Field(..., max_length=255)
    redis_credentials_secret_arn: str = Field(..., max_length=512)
    bedrock_inference_profile_arn: Optional[str] = Field(None, max_length=512)
    rate_limit_rpm: int = Field(60, ge=1)
    rate_limit_tpm: int = Field(50_000, ge=1)
    sso_provider: str = Field(..., max_length=50)
    sso_config: Dict[str, Any] = Field(default_factory=dict)
    sso_domain_restriction: Optional[str] = Field(None, max_length=100)
    custom_domain: Optional[str] = Field(None, max_length=255)
    # Operator-managed customer logo (data URL). Surfaced unauthenticated
    # by ``GET /api/v1/branding/public`` so the /login page renders the
    # customer's identity before sign-in.
    logo_url: Optional[str] = Field(None)
    feature_flags: Dict[str, Any] = Field(default_factory=dict)
    capacity_limits: CapacityDimensions = Field(
        default_factory=lambda: CapacityDimensions(**DEFAULT_CAPACITY_SHAPE)
    )
    auth_methods: AuthMethods = Field(
        default_factory=lambda: AuthMethods(**DEFAULT_AUTH_METHODS)
    )


class TenantCreate(TenantBase):
    """Payload accepted by ``POST /api/v1/_internal/tenants`` (PR #2+)."""

    # No id, no timestamps — the database fills those. ``capacity_used``
    # starts at zero and is updated by the background usage job, so
    # callers do not get to seed it.


class TenantUpdate(BaseModel):
    """Partial update payload. Slug is immutable — it is part of every
    URL, secret path and DNS name, so renames are a separate workflow.

    ``extra="forbid"`` is deliberate: silently dropping a ``slug`` field
    on a PATCH would make API consumers think they renamed a tenant
    when they actually did nothing.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    tier: Optional[TenantTier] = None
    bedrock_inference_profile_arn: Optional[str] = Field(None, max_length=512)
    rate_limit_rpm: Optional[int] = Field(None, ge=1)
    rate_limit_tpm: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    suspended_at: Optional[datetime] = None
    sso_provider: Optional[str] = Field(None, max_length=50)
    sso_config: Optional[Dict[str, Any]] = None
    sso_domain_restriction: Optional[str] = Field(None, max_length=100)
    custom_domain: Optional[str] = Field(None, max_length=255)
    logo_url: Optional[str] = Field(None)
    feature_flags: Optional[Dict[str, Any]] = None
    capacity_limits: Optional[CapacityDimensions] = None
    auth_methods: Optional[AuthMethods] = None

    @field_validator("suspended_at")
    @classmethod
    def _suspended_at_requires_inactive(
        cls, v: Optional[datetime], info
    ) -> Optional[datetime]:
        # Mirror of the SQL check constraint:
        # ``suspended_at IS NOT NULL`` is only valid with ``is_active=False``.
        # Pydantic v2's ``info.data`` is the other fields already validated.
        if v is not None and info.data.get("is_active") is True:
            raise ValueError(
                "suspended_at cannot be set while is_active is true"
            )
        return v


class TenantRead(TenantBase):
    """Response shape for ``GET /api/v1/_internal/tenants[/{slug}]``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    suspended_at: Optional[datetime]
    capacity_used: CapacityDimensions
    created_at: datetime
    updated_at: datetime
