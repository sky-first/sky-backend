"""Add chat_context TEXT column to agents table.

When an agent is created from the AI chat drawer ("Create agent from
this chat" CTA), the frontend now passes a transcript of the
conversation so the agent keeps that context attached to its runs.
Column is nullable — legacy agents and non-chat-originated creations
leave it empty.

Revision ID: agent_chat_context_20260422
Revises: space_member_role_rename_20260421b
Create Date: 2026-04-22 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


revision = "agent_chat_context_20260422"
down_revision = "space_member_role_rename_20260421b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("chat_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "chat_context")
