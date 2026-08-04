"""Pricing Fase 1 — tenant_plan_limits + enforced commercial tier.

Adds the per-tenant pricing-enforcement table that backs the GBT pre-
deploy pricing model Lucas approved 2026-05-29. See the module
docstring in ``src/models/tenant_plan_limits.py`` for the design
rationale.

Seed policy: every existing row in ``tenant_registry`` gets a default
``foundation`` plan row so the enforcement hooks never hit a missing-
row case (treated as 402 by default would be hostile to in-flight
customers). Single-tenant deployments — where every request resolves
to ``DEFAULT_TENANT_CONTEXT.id`` (``UUID(int=0)``) — also get a seed
row keyed on that sentinel UUID.

Why ``foundation`` as the default rather than ``starter``: GBT and
the two other paying tenants are on Foundation; new contracts default
to Foundation; the Console explicitly downgrades a tenant to Starter
when that's the contracted tier. Defaulting to Starter would
retroactively cap real customers below their contract.

Revision ID: tenant_plan_limits_20260530
Revises: sky_role_owner_20260529
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision = "tenant_plan_limits_20260530"
down_revision = "sky_role_owner_20260529"
branch_labels = None
depends_on = None


# Same JSONB / SQLite shim every other migration uses.
_JSONB_OR_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

# Foundation tier ceilings — mirrored from src/models/tenant_plan_limits.py.
# Kept literal so this migration is self-contained.
FOUNDATION_AGENTS = 10
FOUNDATION_USERS = 25
FOUNDATION_STORAGE_GB = 50
FOUNDATION_QUERIES_PER_MONTH = 10_000

# Sentinel UUID used by DEFAULT_TENANT_CONTEXT (single-tenant mode).
NIL_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("tenant_plan_limits"):
        return

    op.create_table(
        "tenant_plan_limits",
        sa.Column(
            "tenant_id",
            PG_UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "tier",
            sa.String(length=32),
            nullable=False,
            server_default="foundation",
        ),
        sa.Column("max_agents", sa.Integer(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_storage_gb", sa.Integer(), nullable=True),
        sa.Column("max_queries_per_month", sa.Integer(), nullable=True),
        sa.Column(
            "current_agents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "current_users",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "current_storage_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "current_queries_this_month",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "queries_period_start",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_threshold_alerted",
            _JSONB_OR_JSON,
            nullable=False,
            server_default=sa.text("'{}'"),
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
            "tier IN ('starter', 'foundation', 'scale', 'enterprise')",
            name="tenant_plan_limits_tier_check",
        ),
        sa.CheckConstraint(
            "current_agents >= 0",
            name="tenant_plan_limits_agents_nonneg",
        ),
        sa.CheckConstraint(
            "current_users >= 0",
            name="tenant_plan_limits_users_nonneg",
        ),
        sa.CheckConstraint(
            "current_storage_bytes >= 0",
            name="tenant_plan_limits_storage_nonneg",
        ),
        sa.CheckConstraint(
            "current_queries_this_month >= 0",
            name="tenant_plan_limits_queries_nonneg",
        ),
    )

    # Seed: every tenant_registry row gets a foundation plan row.
    # Only runs if tenant_registry exists (it does on staging/prod;
    # may not exist on every test DB but the suite uses a fresh
    # in-memory SQLite with metadata.create_all, not this migration).
    if inspector.has_table("tenant_registry"):
        op.execute(
            sa.text(
                "INSERT INTO tenant_plan_limits "
                "(tenant_id, tier, max_agents, max_users, "
                "max_storage_gb, max_queries_per_month) "
                "SELECT id, 'foundation', "
                f":agents, :users, :storage, :queries "
                "FROM tenant_registry "
                "WHERE id NOT IN (SELECT tenant_id FROM tenant_plan_limits)"
            ).bindparams(
                agents=FOUNDATION_AGENTS,
                users=FOUNDATION_USERS,
                storage=FOUNDATION_STORAGE_GB,
                queries=FOUNDATION_QUERIES_PER_MONTH,
            )
        )

    # Single-tenant deployments resolve every request to the
    # NIL_UUID sentinel — seed that row too so the enforcement
    # hooks never raise on a clean staging boot.
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "INSERT INTO tenant_plan_limits "
                "(tenant_id, tier, max_agents, max_users, "
                "max_storage_gb, max_queries_per_month) "
                "VALUES (:tid, 'foundation', :agents, :users, "
                ":storage, :queries) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ).bindparams(
                tid=NIL_UUID,
                agents=FOUNDATION_AGENTS,
                users=FOUNDATION_USERS,
                storage=FOUNDATION_STORAGE_GB,
                queries=FOUNDATION_QUERIES_PER_MONTH,
            )
        )
    else:
        # SQLite path — no ON CONFLICT, but we already guard on
        # has_table above so re-running the migration is a no-op.
        op.execute(
            sa.text(
                "INSERT INTO tenant_plan_limits "
                "(tenant_id, tier, max_agents, max_users, "
                "max_storage_gb, max_queries_per_month) "
                "VALUES (:tid, 'foundation', :agents, :users, "
                ":storage, :queries)"
            ).bindparams(
                tid=NIL_UUID,
                agents=FOUNDATION_AGENTS,
                users=FOUNDATION_USERS,
                storage=FOUNDATION_STORAGE_GB,
                queries=FOUNDATION_QUERIES_PER_MONTH,
            )
        )


def downgrade() -> None:
    op.drop_table("tenant_plan_limits")
