"""Add AI tables (ai_queries, ai_history, pipelines, chat_messages, ai_responses)

Revision ID: add_ai_tables
Revises: add_space_connections
Create Date: 2025-12-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_ai_tables"
down_revision = "add_space_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- ai_history ----
    op.create_table(
        "ai_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("tags", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_ai_history_user_id", "ai_history", ["user_id"], unique=False)
    op.create_index("idx_ai_history_pinned", "ai_history", ["pinned"], unique=False)
    op.create_index("idx_ai_history_category", "ai_history", ["category"], unique=False)
    op.create_index("idx_ai_history_date", "ai_history", ["date"], unique=False)
    op.create_index("idx_ai_history_user_date", "ai_history", ["user_id", "date"], unique=False)

    # ---- ai_queries ----
    # Create without FK to pipelines first to avoid circular dependency (pipelines -> ai_queries, ai_queries -> pipelines)
    op.create_table(
        "ai_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("widget_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("data_sample", postgresql.JSON(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("configure_data", postgresql.JSON(), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_ai_queries_user_id", "ai_queries", ["user_id"], unique=False)
    op.create_index("idx_ai_queries_widget_id", "ai_queries", ["widget_id"], unique=False)
    op.create_index("idx_ai_queries_status", "ai_queries", ["status"], unique=False)
    op.create_index("idx_ai_queries_created_at", "ai_queries", ["created_at"], unique=False)

    # ---- pipelines ----
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("steps", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("current_step", sa.String(255), nullable=True),
        sa.Column("errors", postgresql.JSON(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["query_id"], ["ai_queries.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_pipelines_query_id", "pipelines", ["query_id"], unique=False)
    op.create_index("idx_pipelines_status", "pipelines", ["status"], unique=False)
    op.create_index("idx_pipelines_started_at", "pipelines", ["started_at"], unique=False)

    # Add the circular FK now that pipelines exists
    op.create_foreign_key(
        "fk_ai_queries_pipeline_id",
        "ai_queries",
        "pipelines",
        ["pipeline_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- chat_messages ----
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("widget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_chat_messages_widget_id", "chat_messages", ["widget_id"], unique=False)
    op.create_index("idx_chat_messages_timestamp", "chat_messages", ["timestamp"], unique=False)

    # ---- ai_responses ----
    op.create_table(
        "ai_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("widget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_ai_responses_widget_id", "ai_responses", ["widget_id"], unique=False)
    op.create_index("idx_ai_responses_is_active", "ai_responses", ["is_active"], unique=False)
    op.create_index("idx_ai_responses_timestamp", "ai_responses", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_ai_responses_timestamp", table_name="ai_responses")
    op.drop_index("idx_ai_responses_is_active", table_name="ai_responses")
    op.drop_index("idx_ai_responses_widget_id", table_name="ai_responses")
    op.drop_table("ai_responses")

    op.drop_index("idx_chat_messages_timestamp", table_name="chat_messages")
    op.drop_index("idx_chat_messages_widget_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_constraint("fk_ai_queries_pipeline_id", "ai_queries", type_="foreignkey")

    op.drop_index("idx_pipelines_started_at", table_name="pipelines")
    op.drop_index("idx_pipelines_status", table_name="pipelines")
    op.drop_index("idx_pipelines_query_id", table_name="pipelines")
    op.drop_table("pipelines")

    op.drop_index("idx_ai_queries_created_at", table_name="ai_queries")
    op.drop_index("idx_ai_queries_status", table_name="ai_queries")
    op.drop_index("idx_ai_queries_widget_id", table_name="ai_queries")
    op.drop_index("idx_ai_queries_user_id", table_name="ai_queries")
    op.drop_table("ai_queries")

    op.drop_index("idx_ai_history_user_date", table_name="ai_history")
    op.drop_index("idx_ai_history_date", table_name="ai_history")
    op.drop_index("idx_ai_history_category", table_name="ai_history")
    op.drop_index("idx_ai_history_pinned", table_name="ai_history")
    op.drop_index("idx_ai_history_user_id", table_name="ai_history")
    op.drop_table("ai_history")


