"""Add AI feedback table (ai_feedback)

Revision ID: add_ai_feedback
Revises: merge_heads_20260108
Create Date: 2026-01-09

Stores user feedback (good/bad + optional comment) associated to an AI query (ai_queries.id).
One feedback per (query_id, user_id), updatable.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_ai_feedback"
down_revision = "merge_heads_20260108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["query_id"], ["ai_queries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("rating IN ('good', 'bad')", name="ck_ai_feedback_rating"),
        sa.UniqueConstraint("query_id", "user_id", name="uq_ai_feedback_query_user"),
    )

    op.create_index(
        "idx_ai_feedback_query_id", "ai_feedback", ["query_id"], unique=False
    )
    op.create_index("idx_ai_feedback_user_id", "ai_feedback", ["user_id"], unique=False)
    op.create_index(
        "idx_ai_feedback_created_at", "ai_feedback", ["created_at"], unique=False
    )


def downgrade() -> None:
    pass
    op.drop_index("idx_ai_feedback_created_at", table_name="ai_feedback")
    op.drop_index("idx_ai_feedback_user_id", table_name="ai_feedback")
    op.drop_index("idx_ai_feedback_query_id", table_name="ai_feedback")
