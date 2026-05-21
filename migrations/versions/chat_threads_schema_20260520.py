"""Chat-threads schema — comment vs question split, thread state.

The chat in the canvas is being rebuilt as a shared, page-scoped
collaboration surface (see chat-threads-master-plan). The existing
``conversations`` + ``messages`` tables already cover page-scoped Q&A;
this migration adds the columns needed for the collaborative semantics:

- ``messages.kind`` — distinguishes ``question`` (owner asks AI) from
  ``ai_response`` (LLM-produced) from ``comment`` (non-owner, never
  fires AI) from ``system`` (pin/resolve audit events). Today the
  ``role`` column already partitions user vs assistant vs system; the
  new ``kind`` column lets us further split the user/assistant axis
  along the comment/question axis without overloading ``role``.

- ``messages.parent_message_id`` — comment threading. A reply to a
  comment points at the comment's id. AI responses point at the
  triggering ``question`` row. Initially the FE renders a flat list
  but the column is here so we never have to migrate again to enable
  inline replies.

- ``messages.incorporated_in_message_id`` — when a comment was bundled
  into an Ask-AI call, set this to the id of the resulting AI response.
  The FE renders "incorporated in AI response #N" badges based on this.

- ``conversations.resolved_at`` — set when the owner (or page editor)
  marks the thread resolved (/resolve command). UI filters resolved
  threads into the "Closed" section.

- ``conversations.pinned_message_id`` — the message highlighted at the
  top of the thread by the owner (/pin command). NULL = nothing pinned.

Idempotent and additive — no data drops, all columns nullable.

Revision ID: chat_threads_schema_20260520
Revises: drop_dashboards_table_20260520
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "chat_threads_schema_20260520"
down_revision = "drop_dashboards_table_20260520"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector, table: str, index: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(i["name"] == index for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ─── messages.kind ──────────────────────────────────────────────────────
    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "kind"
    ):
        op.add_column(
            "messages",
            sa.Column("kind", sa.String(length=20), nullable=True),
        )
        # Backfill from existing role so we don't break old reads:
        #   role='user'      → kind='question' (legacy default; comments
        #                       didn't exist until this migration)
        #   role='assistant' → kind='ai_response'
        #   role='system'    → kind='system'
        op.execute(
            "UPDATE messages SET kind = CASE "
            "  WHEN role = 'assistant' THEN 'ai_response' "
            "  WHEN role = 'system' THEN 'system' "
            "  ELSE 'question' "
            "END WHERE kind IS NULL"
        )
        op.create_index(
            "idx_messages_conversation_kind",
            "messages",
            ["conversation_id", "kind"],
        )

    # ─── messages.parent_message_id ────────────────────────────────────────
    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "parent_message_id"
    ):
        op.add_column(
            "messages",
            sa.Column("parent_message_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_messages_parent_message_id",
            "messages",
            "messages",
            ["parent_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "idx_messages_parent_message_id",
            "messages",
            ["parent_message_id"],
            postgresql_where=sa.text("parent_message_id IS NOT NULL"),
        )

    # ─── messages.incorporated_in_message_id ───────────────────────────────
    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "incorporated_in_message_id"
    ):
        op.add_column(
            "messages",
            sa.Column(
                "incorporated_in_message_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.create_foreign_key(
            "fk_messages_incorporated_in_message_id",
            "messages",
            "messages",
            ["incorporated_in_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "idx_messages_incorporated_in_message_id",
            "messages",
            ["incorporated_in_message_id"],
            postgresql_where=sa.text("incorporated_in_message_id IS NOT NULL"),
        )

    # ─── conversations.resolved_at ─────────────────────────────────────────
    if inspector.has_table("conversations") and not _has_column(
        inspector, "conversations", "resolved_at"
    ):
        op.add_column(
            "conversations",
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ─── conversations.pinned_message_id ───────────────────────────────────
    if inspector.has_table("conversations") and not _has_column(
        inspector, "conversations", "pinned_message_id"
    ):
        op.add_column(
            "conversations",
            sa.Column(
                "pinned_message_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.create_foreign_key(
            "fk_conversations_pinned_message_id",
            "conversations",
            "messages",
            ["pinned_message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "conversations", "pinned_message_id"):
        try:
            op.drop_constraint(
                "fk_conversations_pinned_message_id",
                "conversations",
                type_="foreignkey",
            )
        except Exception:
            pass
        op.drop_column("conversations", "pinned_message_id")

    if _has_column(inspector, "conversations", "resolved_at"):
        op.drop_column("conversations", "resolved_at")

    for col, fk, idx in [
        (
            "incorporated_in_message_id",
            "fk_messages_incorporated_in_message_id",
            "idx_messages_incorporated_in_message_id",
        ),
        (
            "parent_message_id",
            "fk_messages_parent_message_id",
            "idx_messages_parent_message_id",
        ),
    ]:
        if _has_column(inspector, "messages", col):
            try:
                op.drop_index(idx, table_name="messages")
            except Exception:
                pass
            try:
                op.drop_constraint(fk, "messages", type_="foreignkey")
            except Exception:
                pass
            op.drop_column("messages", col)

    if _has_column(inspector, "messages", "kind"):
        try:
            op.drop_index("idx_messages_conversation_kind", table_name="messages")
        except Exception:
            pass
        op.drop_column("messages", "kind")
