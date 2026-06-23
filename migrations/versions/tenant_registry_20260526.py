"""Tenant registry — multi-row table that powers Model B multi-tenancy.

Foundation PR (Projeto A — Phase 1, PR #1). Adds the table only;
no FKs from existing tables, no data backfill, no behaviour change.
The middleware that reads from this table is gated by
``MULTI_TENANT_ENABLED`` and ships in PR #2.

Schema follows ``docs/SkyFirst-Docs/04-technical-specs/02-tenant-implementation-spec.md``
Section 3.2 verbatim, with three deliberate divergences:

* ``slug`` carries a regex check (``^[a-z0-9-]{2,50}$``) — the only thing
  the resolver middleware will trust as a tenant identifier, so it has
  to be safe to embed in hostnames and AWS Secrets Manager paths.
* ``capacity_limits`` and ``capacity_used`` ship with explicit shape
  defaults (``{"agents": 0, "sources": 0, "indexed_gb": 0}``) so a
  freshly-created row is valid without the application having to seed it.
* Soft-suspension uses ``suspended_at`` alone; an active row has
  ``is_active = true`` AND ``suspended_at IS NULL``. A composite check
  enforces the two are not contradicting each other.

Revision ID: tenant_registry_20260526
Revises: message_reactions_20260526
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision = "tenant_registry_20260526"
down_revision = "message_reactions_20260526"
branch_labels = None
depends_on = None


# Kept literal here so the migration is self-contained — mirrors
# ``TenantTier`` in ``src/models/tenant.py``. Order matches the pricing
# ladder in ``01-customer-facing/04-pricing-model.md``.
ALLOWED_TIERS = ("pilot", "foundation", "core", "advanced", "strategic")

# Same fallback dance as ``src/models/agent.py``: SQLite (used by the
# test suite) has no JSONB, so on that dialect we collapse to plain JSON.
_JSONB_OR_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("tenant_registry"):
        return

    op.create_table(
        "tenant_registry",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("db_host", sa.String(length=255), nullable=False),
        sa.Column("db_port", sa.Integer(), nullable=False, server_default="5432"),
        sa.Column("db_name", sa.String(length=63), nullable=False),
        sa.Column("db_credentials_secret_arn", sa.String(length=512), nullable=False),
        sa.Column("redis_host", sa.String(length=255), nullable=False),
        sa.Column("redis_credentials_secret_arn", sa.String(length=512), nullable=False),
        sa.Column("bedrock_inference_profile_arn", sa.String(length=512), nullable=True),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("rate_limit_tpm", sa.Integer(), nullable=False, server_default="50000"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sso_provider", sa.String(length=50), nullable=False),
        sa.Column(
            "sso_config",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("sso_domain_restriction", sa.String(length=100), nullable=True),
        sa.Column("custom_domain", sa.String(length=255), nullable=True),
        sa.Column(
            "feature_flags",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "capacity_limits",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text(
                "'{\"agents\": 0, \"sources\": 0, \"indexed_gb\": 0}'"
            ),
        ),
        sa.Column(
            "capacity_used",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text(
                "'{\"agents\": 0, \"sources\": 0, \"indexed_gb\": 0}'"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"tier IN {ALLOWED_TIERS}",
            name="tenant_registry_tier_check",
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9-]{2,50}$'",
            name="tenant_registry_slug_format_check",
        ),
        sa.CheckConstraint(
            "(is_active = true AND suspended_at IS NULL) "
            "OR (is_active = false)",
            name="tenant_registry_active_suspended_consistency_check",
        ),
        sa.UniqueConstraint("slug", name="uq_tenant_registry_slug"),
        sa.UniqueConstraint(
            "custom_domain", name="uq_tenant_registry_custom_domain"
        ),
    )

    op.create_index(
        "ix_tenant_registry_is_active",
        "tenant_registry",
        ["is_active"],
    )
    op.create_index(
        "ix_tenant_registry_tier",
        "tenant_registry",
        ["tier"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_registry_tier", table_name="tenant_registry")
    op.drop_index("ix_tenant_registry_is_active", table_name="tenant_registry")
    op.drop_table("tenant_registry")
