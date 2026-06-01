"""Create file_uploads and sync_logs tables.

Revision ID: file_uploads_20260601
Revises: audit_action_db_config_20260530
Create Date: 2026-06-01

Models FileUpload and SyncLog existed without a corresponding migration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "file_uploads_20260601"
down_revision = "audit_action_db_config_20260530"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    from alembic.runtime.migration import MigrationContext
    bind = op.get_bind()
    ctx = MigrationContext.configure(bind)
    return name in ctx.dialect.get_table_names(bind)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_table_names()

    if "file_uploads" not in existing:
        op.create_table(
            "file_uploads",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("size", sa.BigInteger, nullable=False),
            sa.Column("url", sa.Text, nullable=False),
            sa.Column("storage", sa.String(50), nullable=False),
            sa.Column(
                "widget_id",
                UUID(as_uuid=True),
                sa.ForeignKey("widgets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("parsed_data", sa.JSON, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("idx_file_uploads_user_id", "file_uploads", ["user_id"])
        op.create_index("idx_file_uploads_widget_id", "file_uploads", ["widget_id"])
        op.create_index("idx_file_uploads_mime_type", "file_uploads", ["mime_type"])
        op.create_index("idx_file_uploads_created_at", "file_uploads", ["created_at"])

    if "sync_logs" not in existing:
        op.create_table(
            "sync_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "connection_id",
                UUID(as_uuid=True),
                sa.ForeignKey("data_connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("records_synced", sa.Integer, nullable=True),
            sa.Column("duration", sa.Integer, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("idx_sync_logs_connection_id", "sync_logs", ["connection_id"])
        op.create_index("idx_sync_logs_started_at", "sync_logs", ["started_at"])
        op.create_index("idx_sync_logs_status", "sync_logs", ["status"])


def downgrade() -> None:
    op.drop_table("sync_logs")
    op.drop_table("file_uploads")
