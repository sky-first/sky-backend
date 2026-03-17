"""Add space_connections table

Revision ID: add_space_connections
Revises: add_dashboard_build_jobs
Create Date: 2025-12-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_space_connections"
down_revision = "add_dashboard_build_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_connections",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["data_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("space_id", "connection_id"),
    )

    op.create_index(
        "idx_space_connections_space_id",
        "space_connections",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        "idx_space_connections_connection_id",
        "space_connections",
        ["connection_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_space_connections_connection_id", table_name="space_connections")
    op.drop_index("idx_space_connections_space_id", table_name="space_connections")
    op.drop_table("space_connections")
