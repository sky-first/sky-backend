"""add_enterprise_relationships

Revision ID: b7d1a2e3f4g5
Revises: 65904bc5a0f4
Create Date: 2026-03-04 15:55:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7d1a2e3f4g5"
down_revision = "65904bc5a0f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_enterprise_relationships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("idx_user_enterprise_relationships_created_by"),
        "user_enterprise_relationships",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    pass
    op.drop_index(
        op.f("idx_user_enterprise_relationships_created_by"),
        table_name="user_enterprise_relationships",
    )
