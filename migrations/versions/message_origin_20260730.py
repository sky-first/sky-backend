"""Voice/text origin on messages (BE-04, Sky Mobile).

Adds ``messages.origin`` so the mobile transcript can show a mic glyph on
spoken turns and History can flip a conversation's voice/text icon. Additive
and backward-compatible: every existing row defaults to 'text'.

(``duration_ms`` already exists on the model, so it is not added here.)

Revision ID: message_origin_20260730
Revises: insight_state_20260730
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "message_origin_20260730"
down_revision = "insight_state_20260730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "origin",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'text'"),
        ),
    )
    op.create_check_constraint("ck_messages_origin", "messages", "origin IN ('text', 'voice')")


def downgrade() -> None:
    op.drop_constraint("ck_messages_origin", "messages", type_="check")
    op.drop_column("messages", "origin")
