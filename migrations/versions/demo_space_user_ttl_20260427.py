"""Add is_demo + demo_expires_at to spaces and users (public demo isolation).

Public demo (Cenário B) provisions a per-visitor Space + guest User on
hitting /demo/signup. The cron job needs both flags to find expired
sandboxes and CASCADE-delete them without touching real customer data.

Revision ID: demo_space_user_ttl_20260427
Revises: relationship_phase6_columns_20260426
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "demo_space_user_ttl_20260427"
down_revision = "relationship_phase6_columns_20260426"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # spaces.is_demo / spaces.demo_expires_at
    op.add_column(
        "spaces",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "spaces",
        sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_spaces_demo_expires",
        "spaces",
        ["demo_expires_at"],
        postgresql_where=sa.text("is_demo = true"),
    )

    # users.is_demo / users.demo_expires_at — same TTL so the cleanup
    # cron can CASCADE the user when the Space goes (deleting the
    # Space cascade-deletes its members, but the User row itself isn't
    # owned by the Space — needs its own delete pass).
    op.add_column(
        "users",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_users_demo_expires",
        "users",
        ["demo_expires_at"],
        postgresql_where=sa.text("is_demo = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_demo_expires", table_name="users")
    op.drop_column("users", "demo_expires_at")
    op.drop_column("users", "is_demo")
    op.drop_index("idx_spaces_demo_expires", table_name="spaces")
    op.drop_column("spaces", "demo_expires_at")
    op.drop_column("spaces", "is_demo")
