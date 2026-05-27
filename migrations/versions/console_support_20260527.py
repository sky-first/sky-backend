"""Console support tickets + impersonation sessions (Projeto B It7).

Two tables:
  * ``console_support_tickets`` — customer-raised tickets the Support
    team works in the Console
  * ``console_impersonation_sessions`` — heavily-audited records of
    Sky-team members impersonating tenant users

Revision ID: console_support_20260527
Revises: console_compliance_20260527
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision = "console_support_20260527"
down_revision = "console_compliance_20260527"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("console_support_tickets"):
        op.create_table(
            "console_support_tickets",
            sa.Column(
                "id",
                PG_UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_slug", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "severity",
                sa.String(length=16),
                nullable=False,
                server_default="medium",
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="open",
            ),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("reporter_email", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "severity IN ('low', 'medium', 'high', 'critical')",
                name="console_support_severity_check",
            ),
            sa.CheckConstraint(
                "status IN ('open', 'in_progress', 'waiting_customer', 'resolved', 'closed')",
                name="console_support_status_check",
            ),
        )
        op.create_index(
            "idx_console_support_tenant_status",
            "console_support_tickets",
            ["tenant_slug", "status"],
        )

    if not inspector.has_table("console_impersonation_sessions"):
        op.create_table(
            "console_impersonation_sessions",
            sa.Column(
                "id",
                PG_UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("tenant_slug", sa.String(length=50), nullable=False),
            sa.Column("target_user_email", sa.String(length=255), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("ticket_id", sa.String(length=36), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("customer_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index(
            "idx_console_imp_actor",
            "console_impersonation_sessions",
            ["actor_email", "started_at"],
        )


def downgrade() -> None:
    op.drop_index("idx_console_imp_actor", table_name="console_impersonation_sessions")
    op.drop_table("console_impersonation_sessions")
    op.drop_index("idx_console_support_tenant_status", table_name="console_support_tickets")
    op.drop_table("console_support_tickets")
