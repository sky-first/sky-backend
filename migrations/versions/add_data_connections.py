"""Add data_connections table

Revision ID: add_data_connections
Revises: add_user_datasets
Create Date: 2025-01-20 11:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_data_connections"
down_revision = "add_user_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data Connections table
    op.create_table(
        "data_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("connector_id", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="inactive"),
        sa.Column("config", postgresql.JSON, nullable=False),
        sa.Column("sync_frequency", sa.String(100), nullable=True),
        sa.Column("last_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_metadata_update", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", postgresql.JSON, nullable=True),
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
        "idx_data_connections_connector_id",
        "data_connections",
        ["connector_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_data_connections_status",
        "data_connections",
        ["status"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_data_connections_created_by",
        "data_connections",
        ["created_by"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_data_connections_last_sync",
        "data_connections",
        ["last_sync"],
        unique=False,
    )

    # Connection Metadata table
    op.create_table(
        "connection_metadata",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tables", postgresql.JSON, nullable=True),
        sa.Column("schemas", postgresql.JSON, nullable=True),
        sa.Column("documents", postgresql.JSON, nullable=True),
        sa.Column("endpoints", postgresql.JSON, nullable=True),
        sa.Column(
            "last_metadata_update",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["data_connections.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "connection_id", name="uq_connection_metadata_connection_id"
        ),
    )
    op.create_index(
        "idx_connection_metadata_connection_id",
        "connection_metadata",
        ["connection_id"],
        unique=False,
    )


def downgrade() -> None:
    pass
