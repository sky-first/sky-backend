"""Add ``reactions`` JSONB column to ``messages``.

Slack-style emoji reactions on chat messages. Stored as a JSON
dictionary mapping emoji → list of user_ids who reacted with it:

    {"👍": ["uuid-1", "uuid-2"], "❤️": ["uuid-3"]}

Counts and "did I react?" lookups are O(1) on this shape. NULL or {}
mean "no reactions yet". The default makes the column safe to read
without per-row None guards.

Revision ID: message_reactions_20260526
Revises: change_requests_table_20260520
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "message_reactions_20260526"
down_revision = "change_requests_table_20260520"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "reactions"
    ):
        op.add_column(
            "messages",
            sa.Column(
                "reactions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "messages", "reactions"):
        op.drop_column("messages", "reactions")
