"""Change requests table — chat ↔ widget bridge.

When a non-owner posts a comment that references a widget (e.g.
``Looks wrong on #3``), the system creates a ``change_request`` row
linking the thread, the comment, and the target widget. The widget
owner sees an orange pill (``X pending changes``) on the canvas;
clicking opens the originating thread. Owner accepts (re-runs AI
with the new context) or dismisses (pill clears).

A change request is fully derived from existing rows (message_id +
widget_id) so we keep state minimal — only the lifecycle status and
the dismissal/acceptance metadata live here.

Status enum (varchar, additive):
  - ``pending``   newly created, awaiting widget owner attention
  - ``accepted``  widget owner re-ran AI with this context
  - ``dismissed`` widget owner closed without acting

Indexes:
  - (widget_id, status='pending') so the FE pill query is a single seek
  - (conversation_id) so the thread-side render is a single seek

Revision ID: change_requests_table_20260520
Revises: chat_threads_schema_20260520
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "change_requests_table_20260520"
down_revision = "chat_threads_schema_20260520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("change_requests"):
        op.create_table(
            "change_requests",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "widget_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("widgets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "conversation_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "message_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("messages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "requester_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "resolved_by",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'accepted', 'dismissed')",
                name="ck_change_requests_status_valid",
            ),
        )
        op.create_index(
            "idx_change_requests_widget_pending",
            "change_requests",
            ["widget_id"],
            postgresql_where=sa.text("status = 'pending'"),
        )
        op.create_index(
            "idx_change_requests_conversation",
            "change_requests",
            ["conversation_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("change_requests"):
        op.drop_index("idx_change_requests_conversation", table_name="change_requests")
        op.drop_index("idx_change_requests_widget_pending", table_name="change_requests")
        op.drop_table("change_requests")
