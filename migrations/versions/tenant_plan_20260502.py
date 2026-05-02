"""Tenant plan tier — singleton table replacing the hardcoded "starter"
fallback in plan_for_user.

Same singleton pattern as platform_branding: id always 1. We're still a
single-tenant app today, so threading a tenant_id through the read path
is overkill. When real multi-tenancy ships, this evolves into a per-row
table keyed on tenant_id (and the existing row migrates to whichever
tenant the deployment becomes).

The default tier is `enterprise` so any contracted dev/staging/prod
environment immediately reflects the actual contract instead of the
old `starter` fallback that produced misleading "Upgrade to Pro for 6×
more capacity" copy in the topbar.

Revision ID: tenant_plan_20260502
Revises: beat_consumption_20260502
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "tenant_plan_20260502"
down_revision = "beat_consumption_20260502"
branch_labels = None
depends_on = None


# Mirrors PlanTier in src/config/plan_quotas.py — kept literal here so
# the migration is self-contained and can run without app-side imports.
ALLOWED_TIERS = ("demo", "free", "starter", "pro", "enterprise")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("tenant_plan"):
        return

    op.create_table(
        "tenant_plan",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column(
            "plan_tier",
            sa.String(length=32),
            nullable=False,
            server_default="enterprise",
        ),
        sa.Column("updated_by_user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"plan_tier IN {ALLOWED_TIERS}",
            name="tenant_plan_tier_check",
        ),
    )

    # Seed the singleton row so app-side reads never hit "no row" and
    # have to special-case it. The default value mirrors what the
    # contracted enterprise customer expects to see.
    op.execute(
        sa.text(
            "INSERT INTO tenant_plan (id, plan_tier) VALUES (1, 'enterprise') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_table("tenant_plan")
