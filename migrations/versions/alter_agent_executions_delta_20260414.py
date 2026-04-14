"""Agent executions get delta-detection, cost metering and notification audit.

Each row in agent_executions records one run. Today it stores `answer`,
`sql_executed`, `cycles_consumed`, `findings_count`. The delta pipeline
needs explicit fields so the UI and audit can query them without parsing
the free-text answer.

Columns added:
  - result_hash       — sha256 of the normalised result set (short-circuits
                        the expensive LLM diff when the answer is identical)
  - result_payload    — the raw rows/schema for the most recent 30 runs per
                        agent; older runs have this nulled by the retention job
  - delta_kind        — 'none' | 'trivial' | 'material' | 'first_run'
  - delta_summary     — LLM narrative when material
  - delta_tokens      — tokens spent on the LLM diff call
  - delta_cost_usd    — USD estimate of the diff call
  - llm_tokens_used   — tokens for the main execution (orchestrator +
                        specialist + formatter combined)
  - llm_cost_usd      — USD estimate for the main execution
  - triggered_by_sp_id— which service principal ran this (null for user-owned)
  - attributed_to_user_id — always agents.created_by at run time (even if user
                        has since left the org); preserved for audit
  - notification_id   — the notification emitted, if any
  - duration_ms       — convenience; already derivable from started/finished

Revision ID: exec_delta_20260414
Revises: agents_insight_20260414
Create Date: 2026-04-14 14:20:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "exec_delta_20260414"
down_revision = "agents_insight_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Result + delta ---
    op.add_column(
        "agent_executions",
        sa.Column("result_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("result_payload", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("delta_kind", sa.String(20), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("delta_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("delta_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("delta_cost_usd", sa.Numeric(10, 4), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_executions_delta_kind_valid",
        "agent_executions",
        "delta_kind IS NULL OR delta_kind IN ('first_run', 'none', 'trivial', 'material')",
    )

    # --- Main-execution cost ---
    op.add_column(
        "agent_executions",
        sa.Column("llm_tokens_used", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_executions",
        sa.Column("llm_cost_usd", sa.Numeric(10, 4), nullable=True),
    )

    # --- Identity audit ---
    op.add_column(
        "agent_executions",
        sa.Column(
            "triggered_by_sp_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_principals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_executions",
        sa.Column(
            "attributed_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- Notification audit ---
    op.add_column(
        "agent_executions",
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- Convenience ---
    op.add_column(
        "agent_executions",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )

    # Lookups
    op.create_index(
        "idx_agent_executions_agent_started",
        "agent_executions",
        ["agent_id", "started_at"],
    )
    op.create_index(
        "idx_agent_executions_delta_kind",
        "agent_executions",
        ["delta_kind"],
        postgresql_where=sa.text("delta_kind = 'material'"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_executions_delta_kind", table_name="agent_executions")
    op.drop_index("idx_agent_executions_agent_started", table_name="agent_executions")
    op.drop_column("agent_executions", "duration_ms")
    op.drop_column("agent_executions", "notification_id")
    op.drop_column("agent_executions", "attributed_to_user_id")
    op.drop_column("agent_executions", "triggered_by_sp_id")
    op.drop_column("agent_executions", "llm_cost_usd")
    op.drop_column("agent_executions", "llm_tokens_used")
    op.drop_constraint(
        "ck_agent_executions_delta_kind_valid",
        "agent_executions",
        type_="check",
    )
    op.drop_column("agent_executions", "delta_cost_usd")
    op.drop_column("agent_executions", "delta_tokens")
    op.drop_column("agent_executions", "delta_summary")
    op.drop_column("agent_executions", "delta_kind")
    op.drop_column("agent_executions", "result_payload")
    op.drop_column("agent_executions", "result_hash")
