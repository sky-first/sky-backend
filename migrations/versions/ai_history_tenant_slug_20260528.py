"""Add tenant_slug to ai_history for console per-tenant activity

Revision ID: ai_history_tenant_slug_20260528
Revises: console_support_20260527
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ai_history_tenant_slug_20260528"
down_revision = "console_support_20260527"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {col["name"] for col in inspector.get_columns("ai_history")}
    if "tenant_slug" not in existing_cols:
        op.add_column(
            "ai_history",
            sa.Column("tenant_slug", sa.String(length=50), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("ai_history")}

    if "idx_ai_history_tenant_slug" not in existing_indexes:
        op.create_index(
            "idx_ai_history_tenant_slug",
            "ai_history",
            ["tenant_slug"],
        )

    if "idx_ai_history_tenant_date" not in existing_indexes:
        op.create_index(
            "idx_ai_history_tenant_date",
            "ai_history",
            ["tenant_slug", sa.text("date DESC")],
        )


def downgrade() -> None:
    op.drop_index("idx_ai_history_tenant_date", table_name="ai_history")
    op.drop_index("idx_ai_history_tenant_slug", table_name="ai_history")
    op.drop_column("ai_history", "tenant_slug")
