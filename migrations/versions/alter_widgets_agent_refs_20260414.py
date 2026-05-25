"""Widgets get agent attribution and conversation back-references.

Adds five nullable columns to widgets:
  - conversation_id       → the conversation the widget was pinned from
  - pinned_message_id     → the exact assistant message that was pinned
  - created_by            → the human who created it (for insights born from chat)
  - created_by_sp_id      → set instead of created_by for service-principal-owned
  - created_by_agent_id   → set when the widget was materialised by an agent run

Invariant (enforced in service code, not as a DB check): exactly one of
`created_by` / `created_by_sp_id` is populated for new rows. Pre-existing rows
keep both null — the enforcement only applies to newly written rows.

Revision ID: widgets_agent_refs_20260414
Revises: conv_msg_20260414
Create Date: 2026-04-14 14:05:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "widgets_agent_refs_20260414"
down_revision = "conv_msg_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "pinned_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "created_by_sp_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_principals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "widgets",
        sa.Column(
            "created_by_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Indexes to support typical lookups: "show me all widgets an agent produced"
    # and "show me the widgets pinned out of this conversation".
    op.create_index(
        "idx_widgets_conversation_id",
        "widgets",
        ["conversation_id"],
        postgresql_where=sa.text("conversation_id IS NOT NULL"),
    )
    op.create_index(
        "idx_widgets_created_by_agent_id",
        "widgets",
        ["created_by_agent_id"],
        postgresql_where=sa.text("created_by_agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_widgets_created_by_agent_id", table_name="widgets")
    op.drop_index("idx_widgets_conversation_id", table_name="widgets")
    op.drop_column("widgets", "created_by_agent_id")
    op.drop_column("widgets", "created_by_sp_id")
    op.drop_column("widgets", "created_by")
    op.drop_column("widgets", "pinned_message_id")
    op.drop_column("widgets", "conversation_id")
