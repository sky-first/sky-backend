"""Insights tier classification on agent_executions and messages.

Adds a `tier` column ('l1' | 'l2' | 'l3') so the Settings → Analytics
page can show that not every chat/agent run is the same kind of insight:

- L1 — Delta / trivial: short chat, agent run with no findings.
- L2 — Triage: chat with retrieval, agent that detected something.
- L3 — Deep dive: multi-step chat with plan, agent cross-source correlation.

Also adds `duration_ms` to messages so we can compute a proper
time-to-insight for chat (agent_executions already has duration_ms).

Idempotent (defensive against partially-applied state) and
backwards-compatible — both columns are nullable, classifier writes
forward; historic rows stay NULL until the analytics aggregator hits
them, where NULL falls back to L1.

Revision ID: insights_tier_20260504
Revises: tenant_plan_20260502
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "insights_tier_20260504"
down_revision = "tenant_plan_20260502"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("agent_executions") and not _has_column(
        inspector, "agent_executions", "tier"
    ):
        op.add_column(
            "agent_executions",
            sa.Column("tier", sa.String(length=2), nullable=True),
        )
        op.create_index(
            "idx_agent_executions_tier",
            "agent_executions",
            ["tier"],
        )

    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "tier"
    ):
        op.add_column(
            "messages",
            sa.Column("tier", sa.String(length=2), nullable=True),
        )
        op.create_index("idx_messages_tier", "messages", ["tier"])

    if inspector.has_table("messages") and not _has_column(
        inspector, "messages", "duration_ms"
    ):
        op.add_column(
            "messages",
            sa.Column("duration_ms", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "messages", "duration_ms"):
        op.drop_column("messages", "duration_ms")
    if _has_column(inspector, "messages", "tier"):
        try:
            op.drop_index("idx_messages_tier", table_name="messages")
        except Exception:
            pass
        op.drop_column("messages", "tier")
    if _has_column(inspector, "agent_executions", "tier"):
        try:
            op.drop_index("idx_agent_executions_tier", table_name="agent_executions")
        except Exception:
            pass
        op.drop_column("agent_executions", "tier")
