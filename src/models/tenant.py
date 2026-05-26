"""Tenant registry — multi-row table powering Model B multi-tenancy.

This module is loaded by ``src.config.database.Base`` so the tests'
``Base.metadata.create_all`` picks it up; the runtime middleware that
actually queries it is gated by ``settings.MULTI_TENANT_ENABLED`` and
ships in a later PR.

The slug format regex (``^[a-z0-9-]{2,50}$``) is **not** added as a
SQLAlchemy ``CheckConstraint`` here — SQLite's CHECK does not support
the Postgres ``~`` operator without loading an extension, and forcing
the constraint at the ORM layer would make the test suite fail to
create the table. The Postgres migration enforces it server-side and
the Pydantic schema enforces it at the API boundary, which is the only
place untrusted slugs ever enter.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base


# Same SQLite-friendly JSONB shim used elsewhere (see ``models/agent.py``).
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class TenantTier(str, Enum):
    """Pricing tiers — see ``01-customer-facing/04-pricing-model.md``."""

    PILOT = "pilot"
    FOUNDATION = "foundation"
    CORE = "core"
    ADVANCED = "advanced"
    STRATEGIC = "strategic"


# Coarse default capacity shape — every row is created with these keys so
# downstream code never has to ``.get("agents", 0)`` defensively.
DEFAULT_CAPACITY_SHAPE = {"agents": 0, "sources": 0, "indexed_gb": 0}


class Tenant(Base):
    """A customer workspace registered in the platform tenant registry.

    One row per tenant. Connection details (DB host, secrets ARN, SSO
    config) are stored here so the tenant resolver middleware can build
    a per-tenant session on demand. Compute (sky-be, sky-ai pods) is
    shared across tenants under Model B; data layer (Postgres, Redis)
    is dedicated per tenant.
    """

    __tablename__ = "tenant_registry"

    # ── Identity ──────────────────────────────────────────────────
    # ``server_default=gen_random_uuid()`` lives in the Postgres
    # migration; SQLite (test suite) has no such function, so we rely on
    # the Python-side ``default=uuid.uuid4`` at the ORM layer. The
    # ``UUID(as_uuid=True)`` type implements a TypeDecorator that
    # transparently round-trips through CHAR(32) on SQLite, matching the
    # pattern used by every other model in the codebase.
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    slug = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=False)
    tier = Column(String(20), nullable=False)

    # ── Data plane (per-tenant dedicated Postgres + Redis pods) ──
    db_host = Column(String(255), nullable=False)
    db_port = Column(Integer, nullable=False, server_default="5432")
    db_name = Column(String(63), nullable=False)
    db_credentials_secret_arn = Column(String(512), nullable=False)
    redis_host = Column(String(255), nullable=False)
    redis_credentials_secret_arn = Column(String(512), nullable=False)

    # ── Optional per-tenant Bedrock inference profile ────────────
    # Populated only when total Bedrock spend justifies per-tenant
    # cost tracking (see ``04-technical-specs/04-bedrock-multi-tenant-spec.md``).
    bedrock_inference_profile_arn = Column(String(512), nullable=True)

    # ── Rate limiting (per-tenant ceilings) ──────────────────────
    rate_limit_rpm = Column(Integer, nullable=False, server_default="60")
    rate_limit_tpm = Column(Integer, nullable=False, server_default="50000")

    # ── Lifecycle ────────────────────────────────────────────────
    # Active means "the resolver will route traffic here". Suspended
    # means "blocked on billing or compliance hold". The check
    # constraint forbids the contradictory state
    # ``is_active=true AND suspended_at IS NOT NULL``.
    is_active = Column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    suspended_at = Column(DateTime(timezone=True), nullable=True)

    # ── SSO ──────────────────────────────────────────────────────
    sso_provider = Column(String(50), nullable=False)
    sso_config = Column(_JSONB_OR_JSON, nullable=False, default=dict)
    sso_domain_restriction = Column(String(100), nullable=True)

    # ── Branding ─────────────────────────────────────────────────
    custom_domain = Column(String(255), nullable=True)

    # ── Capability flags + capacity bookkeeping ──────────────────
    feature_flags = Column(_JSONB_OR_JSON, nullable=False, default=dict)
    capacity_limits = Column(
        _JSONB_OR_JSON, nullable=False, default=lambda: dict(DEFAULT_CAPACITY_SHAPE)
    )
    # ``capacity_used`` is updated by a background job — see PR #4+.
    capacity_used = Column(
        _JSONB_OR_JSON, nullable=False, default=lambda: dict(DEFAULT_CAPACITY_SHAPE)
    )

    # ── Audit ────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenant_registry_slug"),
        UniqueConstraint("custom_domain", name="uq_tenant_registry_custom_domain"),
        CheckConstraint(
            "tier IN ('pilot', 'foundation', 'core', 'advanced', 'strategic')",
            name="tenant_registry_tier_check",
        ),
        # Stated as "if active, must not be suspended" — equivalent to
        # ``(is_active AND suspended_at IS NULL) OR NOT is_active`` but
        # avoids the ``true`` / ``false`` literals SQLite does not accept
        # in CHECK constraints. Postgres still gets the same semantics.
        CheckConstraint(
            "(is_active AND suspended_at IS NULL) OR NOT is_active",
            name="tenant_registry_active_suspended_consistency_check",
        ),
        Index("ix_tenant_registry_is_active", "is_active"),
        Index("ix_tenant_registry_tier", "tier"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"<Tenant slug={self.slug!r} tier={self.tier!r} active={self.is_active}>"
