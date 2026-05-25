"""Platform branding — owner-controlled tenant-wide visual config.

Single-row table (id always 1) so the read path doesn't need to thread
a tenant_id through. Owner-only writes; reads open to any authenticated
user (they need the config on app boot to render the right theme).

Revision ID: platform_branding_20260425
Revises: tickets_20260425
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "platform_branding_20260425"
down_revision = "tickets_20260425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("platform_branding"):
        # Idempotent — if a previous local hand-fix already created the
        # table, skip without error so the migration head still advances.
        return

    op.create_table(
        "platform_branding",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column(
            "primary_color",
            sa.String(length=9),
            nullable=False,
            server_default="#1e3a5f",
        ),
        sa.Column("radius", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "font_family",
            sa.String(length=32),
            nullable=False,
            server_default="geist",
        ),
        # JSON so we can later evolve to ``{light: ..., dark: ...}`` without
        # another migration. Nullable since fresh tenants have no logo.
        sa.Column("logo_url", sa.JSON(), nullable=True),
        sa.Column(
            "company_name",
            sa.String(length=255),
            nullable=False,
            server_default="SkyFirstLabs",
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
    )


def downgrade() -> None:
    op.drop_table("platform_branding")
