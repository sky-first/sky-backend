"""add enterprise apis table

Revision ID: 380964cb0112
Revises: 4ee65fd7eb1f
Create Date: 2026-03-12 14:52:33.697101

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "380964cb0112"
down_revision = "4ee65fd7eb1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_apis",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("endpoints", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("idx_enterprise_apis_created_by"),
        "enterprise_apis",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    pass
    op.drop_index(op.f("idx_enterprise_apis_created_by"), table_name="enterprise_apis")
