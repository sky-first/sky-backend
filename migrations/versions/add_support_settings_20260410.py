"""Add support_settings and support_sessions tables for Sky Support JIT.

Revision ID: add_support_settings_20260410
Revises: add_service_principals_20260410
Create Date: 2026-04-10 22:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_support_settings_20260410"
down_revision = "add_service_principals_20260410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deploy-level support settings (one row per deploy)
    op.create_table(
        "support_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("access_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("require_ticket_id", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("allowed_modes", sa.ARRAY(sa.String), nullable=False, server_default="{read_only,read_write_no_data}"),
        sa.Column("auto_revoke_after_minutes", sa.Integer, nullable=False, server_default="240"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Insert default row
    op.execute("""
        INSERT INTO support_settings (access_enabled, require_ticket_id)
        VALUES (true, false)
    """)

    # JIT support sessions
    op.create_table(
        "support_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operator_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", sa.String(100), nullable=True),
        sa.Column("mode", sa.String(50), nullable=False),
        sa.Column("justification", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_support_sessions_operator", "support_sessions", ["operator_id"])
    op.create_index("idx_support_sessions_active", "support_sessions", ["expires_at"],
                     postgresql_where=sa.text("revoked_at IS NULL"))


def downgrade() -> None:
    op.drop_index("idx_support_sessions_active", table_name="support_sessions")
    op.drop_index("idx_support_sessions_operator", table_name="support_sessions")
    op.drop_table("support_sessions")
    op.drop_table("support_settings")
