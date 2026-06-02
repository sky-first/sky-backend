"""Add ``user_id`` author column to ``messages``.

Chat messages previously stored no author, so in a shared (space/crew)
chat every collaborator saw their OWN name on every message — the
frontend fell back to the local user because the message carried no
identity. This adds the writer's user id to each message so the real
author can be attributed to everyone.

- ``user_id`` → FK ``users.id`` ON DELETE SET NULL (keep the message if
  the account is removed). NULL for assistant/system messages and for
  legacy rows we can't attribute.
- Backfill: existing ``role='user'`` rows are attributed to their
  conversation's ``created_by`` (the owner who asked the question — the
  overwhelming majority of legacy user messages). Comments by non-owners
  in old shared threads are effectively non-existent (collaborative chat
  just shipped), so this is safe and fixes attribution for existing
  threads immediately.

Revision ID: messages_user_id_20260602
Revises: file_uploads_20260601
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "messages_user_id_20260602"
down_revision = "file_uploads_20260601"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector, table: str, index: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("messages"):
        return

    if not _has_column(inspector, "messages", "user_id"):
        op.add_column(
            "messages",
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    if not _has_index(inspector, "messages", "ix_messages_user_id"):
        op.create_index("ix_messages_user_id", "messages", ["user_id"])

    # Best-effort backfill: attribute legacy user messages to the
    # conversation owner. Skipped silently if the conversations table is
    # absent (shouldn't happen in prod).
    if inspector.has_table("conversations"):
        op.execute(
            sa.text(
                """
                UPDATE messages AS m
                SET user_id = c.created_by
                FROM conversations AS c
                WHERE m.conversation_id = c.id
                  AND m.user_id IS NULL
                  AND m.role = 'user'
                  AND c.created_by IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "messages", "ix_messages_user_id"):
        op.drop_index("ix_messages_user_id", table_name="messages")

    if _has_column(inspector, "messages", "user_id"):
        op.drop_column("messages", "user_id")
