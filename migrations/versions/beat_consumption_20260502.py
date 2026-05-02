"""Beat consumption — append-only log for AI cost / quota tracking.

Beats are the unified usage currency across chat, agents (L1/L2/L3) and
ancillary AI calls (suggest_title, etc.). Each row is one consumption
event; aggregates (per user, per tenant, per period) are computed
on-demand by ``BeatsService.usage_window`` over a rolling window
defined by the active plan.

Why append-only:
  • No reset cron — the rolling window does the right thing for any
    period (demo 7d, paid 30d).
  • Both per-user and per-tenant aggregates derive from the same log.
  • Future export / billing audit trail without extra plumbing.

Revision ID: beat_consumption_20260502
Revises: normalize_member_roles_phase7_20260501
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "beat_consumption_20260502"
down_revision = "normalize_member_roles_phase7_20260501"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    UUID_TYPE = sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36)

    # The kind enum is intentionally OPEN — stored as TEXT so we can add
    # tiers (agent_l1, agent_l2, agent_l3) without an enum migration when
    # the agent tier-router lands. Validation happens at the application
    # layer (BeatsService.KIND_COSTS).
    op.create_table(
        "beat_consumption",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "user_id",
            UUID_TYPE,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # tenant_id stays nullable until the multi-tenant model lands —
        # today every user is in the single Sky tenant. Foreign key is
        # added now so the schema is right for v1; the column is
        # populated as the user.tenant_id mapping ships.
        sa.Column(
            "tenant_id",
            UUID_TYPE,
            nullable=True,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "source_id",
            UUID_TYPE,
            nullable=True,
            comment="Optional pointer to the originating row (ai_query.id, agent_run.id, …)",
        ),
        sa.Column(
            "beats",
            sa.Numeric(8, 2),
            nullable=False,
            comment="Cost of this event in beats. L2-normalised (1 beat = 1 gpt-4o-mini call equivalent).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Hot path is "SUM(beats) WHERE user_id=? AND created_at >= ?", so the
    # composite index on (user_id, created_at DESC) is what carries the
    # quota check. Tenant aggregate rides on tenant_id index.
    op.create_index(
        "idx_beat_consumption_user_time",
        "beat_consumption",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_beat_consumption_tenant_time",
        "beat_consumption",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_beat_consumption_kind",
        "beat_consumption",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index("idx_beat_consumption_kind", table_name="beat_consumption")
    op.drop_index("idx_beat_consumption_tenant_time", table_name="beat_consumption")
    op.drop_index("idx_beat_consumption_user_time", table_name="beat_consumption")
    op.drop_table("beat_consumption")
