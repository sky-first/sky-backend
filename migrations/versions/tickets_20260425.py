"""Tickets — customer-raised support tickets.

Two tables:

  - ``tickets``        — header (reporter, space, status, category, severity)
  - ``ticket_events``  — append-only timeline (created, commented,
                          status_changed, assigned, escalated, ...)

Distinct from ``support_sessions`` (operator JIT). Customer-facing.

Revision ID: tickets_20260425
Revises: context_acl_w1_20260424
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tickets_20260425"
down_revision = "context_acl_w1_20260424"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    UUID_TYPE = sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36)
    JSON_TYPE = sa.dialects.postgresql.JSONB if pg else sa.JSON
    JSON_DEFAULT = sa.text("'{}'::jsonb") if pg else sa.text("'{}'")

    op.create_table(
        "tickets",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "reporter_user_id",
            UUID_TYPE,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "space_id",
            UUID_TYPE,
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("category", sa.String(32), nullable=False, server_default="other"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column(
            "assigned_to_user_id",
            UUID_TYPE,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "escalated_by_user_id",
            UUID_TYPE,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_ref", sa.String(64), nullable=True),
        sa.Column("context_jsonb", JSON_TYPE, nullable=False, server_default=JSON_DEFAULT),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category in ('chat_error','agent_error','bug','feature_request','security','other')",
            name="ck_tickets_category",
        ),
        sa.CheckConstraint(
            "severity in ('low','medium','high','critical')",
            name="ck_tickets_severity",
        ),
        sa.CheckConstraint(
            "status in ('open','in_progress','resolved','closed','escalated')",
            name="ck_tickets_status",
        ),
    )
    op.create_index("ix_tickets_reporter", "tickets", ["reporter_user_id"])
    op.create_index("ix_tickets_space", "tickets", ["space_id"])
    op.create_index("ix_tickets_status_created", "tickets", ["status", "created_at"])

    op.create_table(
        "ticket_events",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "ticket_id",
            UUID_TYPE,
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            UUID_TYPE,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "payload_jsonb",
            JSON_TYPE,
            nullable=False,
            server_default=JSON_DEFAULT,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind in ('created','commented','status_changed','assigned',"
            "'escalated','resolved','reopened')",
            name="ck_ticket_events_kind",
        ),
    )
    op.create_index(
        "ix_ticket_events_ticket_created",
        "ticket_events",
        ["ticket_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_events_ticket_created", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index("ix_tickets_status_created", table_name="tickets")
    op.drop_index("ix_tickets_space", table_name="tickets")
    op.drop_index("ix_tickets_reporter", table_name="tickets")
    op.drop_table("tickets")
