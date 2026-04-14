"""Extend agents for insight mode, service principal identity, and a flexible schedule.

The existing `agents` table (from `create_agents_20260401`) supports
`question`, `datasource`, and `sql` monitor_types with a coarse `frequency`
enum (hourly/daily/weekly). The unified agent primitive adds:

  - `insight` monitor_type — an agent bound to a specific widget, re-running
    that insight's query on schedule.
  - Identity model — agents can run as the creator user OR as a service
    principal (required so collaborative agents survive the creator leaving
    the crew/space).
  - Flexible schedule — `schedule_jsonb` carries interval value + unit +
    optional `ends_at`, replacing the coarse `frequency` enum over time.
    `frequency` is kept for backward compat so existing rows still work.
  - Conversation linkage — agents can append system messages into a
    conversation so scheduled updates live in the thread.

All new columns are nullable so existing rows remain valid. Application code
is responsible for populating the new fields on newly created agents.

Revision ID: agents_insight_20260414
Revises: sp_spaces_20260414
Create Date: 2026-04-14 14:15:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "agents_insight_20260414"
down_revision = "sp_spaces_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Identity ---
    # identity_type is either 'user' or 'service_principal'. Legacy rows get
    # 'user' by default so behaviour stays identical.
    op.add_column(
        "agents",
        sa.Column(
            "identity_type",
            sa.String(20),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "service_principal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_principals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_agents_identity_type_valid",
        "agents",
        "identity_type IN ('user', 'service_principal')",
    )

    # --- Insight mode ---
    # widget_id + conversation_id link the agent back to the insight it
    # re-runs and the thread it narrates updates into.
    op.add_column(
        "agents",
        sa.Column(
            "widget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("widgets.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_agents_widget_id",
        "agents",
        ["widget_id"],
        postgresql_where=sa.text("widget_id IS NOT NULL"),
    )

    # --- Flexible schedule ---
    # schedule_jsonb shape: {
    #   "interval_value": 5,
    #   "interval_unit": "minute" | "hour" | "day" | "week",
    #   "timezone": "UTC" (optional)
    # }
    # ends_at is a separate column because we want to index on it for
    # "auto-end when past-due" sweeps.
    op.add_column(
        "agents",
        sa.Column(
            "schedule_jsonb",
            postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "ends_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_agents_ends_at",
        "agents",
        ["ends_at"],
        postgresql_where=sa.text("ends_at IS NOT NULL"),
    )

    # --- Delta strategy ---
    # 'hash' | 'llm'. Default 'hash' is cheap; upgrade individual agents to
    # 'llm' when they carry a human question whose narrative matters.
    op.add_column(
        "agents",
        sa.Column(
            "delta_strategy",
            sa.String(10),
            nullable=False,
            server_default="hash",
        ),
    )
    op.create_check_constraint(
        "ck_agents_delta_strategy_valid",
        "agents",
        "delta_strategy IN ('hash', 'llm')",
    )

    # --- Notify-on-change ---
    op.add_column(
        "agents",
        sa.Column(
            "notify_on_change",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # --- Retry budget state (resets after success) ---
    op.add_column(
        "agents",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "consecutive_failures")
    op.drop_column("agents", "notify_on_change")
    op.drop_constraint("ck_agents_delta_strategy_valid", "agents", type_="check")
    op.drop_column("agents", "delta_strategy")
    op.drop_index("idx_agents_ends_at", table_name="agents")
    op.drop_column("agents", "ends_at")
    op.drop_column("agents", "schedule_jsonb")
    op.drop_index("idx_agents_widget_id", table_name="agents")
    op.drop_column("agents", "conversation_id")
    op.drop_column("agents", "widget_id")
    op.drop_constraint("ck_agents_identity_type_valid", "agents", type_="check")
    op.drop_column("agents", "service_principal_id")
    op.drop_column("agents", "identity_type")
