"""Add conversations and messages tables.

Conversations are the first-class thread of Q&A within a page. A conversation
can spawn many widgets (via pinning specific messages) and an agent can be
pinned to re-run against a conversation so that scheduled updates surface as
system messages in the thread.

This migration is schema-only — no application code reads or writes these
tables yet. The agent runtime (Phase 1 onwards) will start using them.

Revision ID: conv_msg_20260414
Revises: backfill_creator_membership_20260414
Create Date: 2026-04-14 14:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision = "conv_msg_20260414"
down_revision = "backfill_creator_membership_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── conversations ──────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crews.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_conversations_page_updated",
        "conversations",
        ["page_id", "updated_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "idx_conversations_space_id",
        "conversations",
        ["space_id"],
        postgresql_where=sa.text("space_id IS NOT NULL"),
    )
    op.create_index(
        "idx_conversations_crew_id",
        "conversations",
        ["crew_id"],
        postgresql_where=sa.text("crew_id IS NOT NULL"),
    )

    # ── messages ───────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="'user' | 'assistant' | 'system'",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "query_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_queries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cost_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "pinned_widget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("widgets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_check_constraint(
        "ck_messages_role_valid",
        "messages",
        "role IN ('user', 'assistant', 'system')",
    )


def downgrade() -> None:
    op.drop_index("idx_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_conversations_crew_id", table_name="conversations")
    op.drop_index("idx_conversations_space_id", table_name="conversations")
    op.drop_index("idx_conversations_page_updated", table_name="conversations")
    op.drop_table("conversations")
