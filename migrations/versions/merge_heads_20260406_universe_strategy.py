"""Merge universe intelligence and strategy m2m migration heads

Revision ID: merge_heads_20260406
Revises: agent_monitor_20260401, dbc6bf507333
Create Date: 2026-04-06 15:00:00.000000

This is a no-op merge migration that unifies two parallel migration heads
that appeared on staging after PR #139 (DO2025-1180 universe intelligence)
was merged. Both heads forked from revision fd74af4b3c14:

  fd74af4b3c14 ──┬─> a3f2c1d0e9b8 ─> create_agents_20260401 ─> agent_monitor_20260401
                 │                   (also merges merge_metrics_head_20260225)
                 └─> d66d838fb734  ─> dbc6bf507333 (strategy_m2m)

This migration reconciles them so `alembic upgrade head` succeeds.
"""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = "merge_heads_20260406"
down_revision = ("agent_monitor_20260401", "dbc6bf507333")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op — this migration only unifies two parallel heads."""
    pass


def downgrade() -> None:
    """No-op — downgrade splits back into two heads."""
    pass
