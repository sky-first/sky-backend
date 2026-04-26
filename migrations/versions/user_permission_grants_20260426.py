"""Create user_permission_grants table (Knowledge refactor — Phase 3).

Backs the delegable ``knowledge.certify`` permission so Owner can grant
Org-write capability to specific admins (CFO, governance lead, …)
without elevating them to tenant Owner.

Revision ID: user_permission_grants_20260426
Revises: metric_table_20260425
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "user_permission_grants_20260426"
down_revision = "metric_table_20260425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_permission_grants" in set(inspector.get_table_names()):
        return  # idempotent

    op.create_table(
        "user_permission_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=100), nullable=False),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_permission_grants_user_permission",
        "user_permission_grants",
        ["user_id", "permission"],
    )
    op.create_index(
        "ix_user_permission_grants_user_id",
        "user_permission_grants",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_permission_grants_user_id", table_name="user_permission_grants"
    )
    op.drop_index(
        "ix_user_permission_grants_user_permission",
        table_name="user_permission_grants",
    )
    op.drop_table("user_permission_grants")
