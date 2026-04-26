"""Create the metrics table (Knowledge refactor — Phase 2).

The Metric model unifies the dropped Pillar / Goal / OKR / KeyResult /
Initiative / Risk / Cycle entities (see Phase 1a) into a single row
with target / threshold / tags / formula attributes. This migration
creates the table only — service / API / FE wiring lands in
follow-up commits and PRs.

Revision ID: metric_table_20260425
Revises: drop_events_signals_20260425
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "metric_table_20260425"
down_revision = "drop_events_signals_20260425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "metrics" in set(inspector.get_table_names()):
        return  # idempotent — bail if a previous run already created it

    op.create_table(
        "metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("formula_text", sa.Text(), nullable=True),
        sa.Column("formula_description", sa.Text(), nullable=True),
        sa.Column(
            "formula_language",
            sa.String(length=20),
            nullable=False,
            server_default="sql",
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_table", sa.String(length=255), nullable=True),
        sa.Column("source_column", sa.String(length=255), nullable=True),
        sa.Column("aggregation", sa.String(length=30), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("time_grain", sa.String(length=20), nullable=True),
        sa.Column("target_value", sa.Numeric(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("threshold_warning", sa.Numeric(), nullable=True),
        sa.Column("threshold_critical", sa.Numeric(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "certified_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("scope", "scope_id", "slug", name="uq_metrics_scope_slug"),
    )
    op.create_index("ix_metrics_scope_scope_id", "metrics", ["scope", "scope_id"])
    op.create_index("ix_metrics_status", "metrics", ["status"])
    op.create_index("ix_metrics_scope_id", "metrics", ["scope_id"])


def downgrade() -> None:
    op.drop_index("ix_metrics_scope_id", table_name="metrics")
    op.drop_index("ix_metrics_status", table_name="metrics")
    op.drop_index("ix_metrics_scope_scope_id", table_name="metrics")
    op.drop_table("metrics")
