"""Add space_members table

Revision ID: a1b2c3d4e5f6
Revises: 86aad48392e8
Create Date: 2025-01-15 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "86aad48392e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create spaces table (new entity, distinct from planets)
    op.create_table(
        "spaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("icon", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_spaces_created_by",
        "spaces",
        ["created_by"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Create space_members table
    op.create_table(
        "space_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # Create indexes
    op.create_index("idx_space_members_space_id", "space_members", ["space_id"])
    op.create_index("idx_space_members_user_id", "space_members", ["user_id"])
    op.create_index(
        "idx_space_members_space_user",
        "space_members",
        ["space_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    pass
    # Drop indexes and tables in reverse order
    # Drop indexes
    op.drop_index("idx_space_members_space_user", table_name="space_members")
    op.drop_index("idx_space_members_user_id", table_name="space_members")
    op.drop_index("idx_space_members_space_id", table_name="space_members")

    # Drop table
    op.drop_index("idx_spaces_created_by", table_name="spaces")
