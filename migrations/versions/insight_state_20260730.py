"""Per-user insight review/pin state (BE-02, Sky Mobile).

One row per (user, finding) holding the user's own reviewed/pinned timestamps
for the mobile Insights feed. Additive; no change to existing tables.

Revision ID: insight_state_20260730
Revises: agent_finding_structured_20260730
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "insight_state_20260730"
down_revision = "agent_finding_structured_20260730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insight_state",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "finding_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "finding_id", name="uq_insight_state_user_finding"),
    )
    op.create_index("idx_insight_state_user", "insight_state", ["user_id"])
    op.create_index("idx_insight_state_finding", "insight_state", ["finding_id"])


def downgrade() -> None:
    op.drop_index("idx_insight_state_finding", table_name="insight_state")
    op.drop_index("idx_insight_state_user", table_name="insight_state")
    op.drop_table("insight_state")
