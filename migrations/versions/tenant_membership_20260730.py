"""Tenant membership registry — central user↔tenant mapping (BE-01, Sky Mobile).

Adds the ``tenant_membership`` table to the platform registry DB. It is the
single source of truth for two mobile-critical questions that DB-per-tenant
identity cannot answer on its own:

* which tenants a user may act as (the workspace switcher), and
* whether a user is *still* a member of a tenant (per-request authorization
  for device clients carrying a signed ``tid`` claim).

Additive only: no FK from existing tables, no data backfill, no behaviour
change. The resolver that reads this table is gated behind
``MULTI_TENANT_ENABLED`` / the device path, exactly like the tenant registry.

Revision ID: tenant_membership_20260730
Revises: seed_gbt_demo_usage_20260624
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "tenant_membership_20260730"
down_revision = "seed_gbt_demo_usage_20260624"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_membership",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # ``users.id`` lives in the per-tenant data plane, so this is a value
        # reference, not a hard FK — the coupling is enforced by the login /
        # off-boarding flows, never by a cross-database constraint.
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("tenant_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'member'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_tenant_membership_user_tenant"),
    )
    op.create_index("idx_tenant_membership_user", "tenant_membership", ["user_id"])
    op.create_index("idx_tenant_membership_tenant", "tenant_membership", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_tenant_membership_tenant", table_name="tenant_membership")
    op.drop_index("idx_tenant_membership_user", table_name="tenant_membership")
    op.drop_table("tenant_membership")
