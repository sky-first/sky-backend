"""Add owner_user_id to signal_events, strategic_pillars, strategic_objectives, strategy_okrs, strategy_key_results, strategy_initiatives.

Lets Personal mode scope these resources to the current user (owner_user_id = user_id, space_id = NULL) so Personal no longer aggregates everything from every Space the user belongs to. Context documents already had owner_user_id.

Nullable on purpose: legacy rows stay space-scoped (owner_user_id IS NULL means "owned by a Space, visible in that Space's scope").

Revision ID: personal_owner_user_id_20260422
Revises: agent_chat_context_20260422
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "personal_owner_user_id_20260422"
down_revision = "agent_chat_context_20260422"
branch_labels = None
depends_on = None


TABLES = [
    "signal_events",
    "strategic_pillars",
    "strategic_objectives",
    "strategy_okrs",
    "strategy_key_results",
    "strategy_initiatives",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "owner_user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(
            f"ix_{table}_owner_user_id",
            table,
            ["owner_user_id"],
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_owner_user_id", table_name=table)
        op.drop_column(table, "owner_user_id")
