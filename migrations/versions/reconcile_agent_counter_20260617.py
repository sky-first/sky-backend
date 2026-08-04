"""reconcile inflated current_agents counter

The tier accounting bumped ``tenant_plan_limits.current_agents`` on agent
creation but never decremented it on deletion (no ``record_agent_deleted``
hook). A tenant that created and deleted N agents stayed pinned at N/N and
could no longer create any agent, even with zero live agents.

This migration recomputes ``current_agents`` from the live ``agents`` row
count so already-inflated tenants are released. The companion code change
(``record_agent_deleted`` + clamp) prevents the counter from drifting again.

Single-tenant today: ``agents`` has no ``tenant_id`` column, so every agent
belongs to the default sentinel tenant and the global row count is the
correct value for the (single) limits row. The WHERE makes it idempotent —
re-running only touches rows whose counter is actually wrong.

Revision ID: reconcile_agent_counter_20260617
Revises: discontinue_space_pages_20260617
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "reconcile_agent_counter_20260617"
down_revision = "discontinue_space_pages_20260617"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "tenant_plan_limits" not in tables or "agents" not in tables:
        return

    op.execute(
        sa.text(
            """
            UPDATE tenant_plan_limits
            SET current_agents = (SELECT COUNT(*) FROM agents)
            WHERE current_agents <> (SELECT COUNT(*) FROM agents)
            """
        )
    )


def downgrade() -> None:
    # No-op: the previous counter value was wrong (inflated), so there is
    # nothing meaningful to restore.
    pass
