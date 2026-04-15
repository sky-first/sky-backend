"""Add duration_ms to ai_history so Settings → Usage can show real latency.

The chat endpoint will populate this on save. Old rows stay NULL and
the metrics endpoint filters them out — no backfill needed.

Revision ID: ai_duration_20260415
Revises: ctx_evidence_20260415
Create Date: 2026-04-15 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "ai_duration_20260415"
down_revision = "ctx_evidence_20260415"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_history",
        sa.Column("duration_ms", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_history", "duration_ms")
