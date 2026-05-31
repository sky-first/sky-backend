"""Create tenant_llm_daily_snapshots table.

Backs :mod:`src.models.tenant_llm_daily_snapshot` — one row per
(tenant, day) materialised daily by the Celery beat task in
``src.workers.llm_metrics_worker``. Source of truth remains Langfuse;
this table is the trend-chart / historical-archive cache so:

* The Console doesn't burn through Langfuse Cloud's rate limit on
  every page load.
* Historical analysis (year-over-year, cohort comparisons) doesn't
  depend on Langfuse retention — 90 days on the free tier.

Unique constraint on (tenant_id, snapshot_date) so the worker can
upsert safely if it has to re-run for the same day. JSONB on the
``by_model_json`` column because the per-model breakdown is best
queried with Postgres's JSONB operators (``->``, ``->>``) when an
operator needs to drill into one model's cost over time.

Revision ID: llm_snapshots_20260530
Revises: provisioning_events_20260530
Create Date: 2026-05-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "llm_snapshots_20260530"
down_revision = "users_mfa_20260530"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _jsonb() -> sa.types.TypeEngine:
    """JSONB on Postgres, plain JSON on SQLite (test suite)."""
    return JSONB().with_variant(sa.JSON(), "sqlite")


def _uuid() -> sa.types.TypeEngine:
    """Postgres UUID, CHAR(36) on SQLite — same shim other tables use."""
    return UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "tenant_llm_daily_snapshots",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "total_requests",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_input_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_output_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_cost_eur",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cache_hit_rate_pct",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "avg_latency_ms",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "by_model_json",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("langfuse_host", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            name="uq_tenant_llm_daily_snapshots_tenant_date",
        ),
    )

    # Two indexes to back the dominant read patterns:
    #   1. Console trend chart — "show me the last 30 rows for tenant X".
    #      The unique constraint above already covers (tenant_id, date)
    #      but Postgres won't necessarily reuse a unique-index for an
    #      ORDER BY snapshot_date DESC scan, so we add a dedicated
    #      composite ordered the right way.
    #   2. Platform-wide rollup — "sum cost across all tenants for the
    #      last 30 days" → scans by date alone.
    op.create_index(
        "idx_tenant_llm_daily_tenant_date_desc",
        "tenant_llm_daily_snapshots",
        ["tenant_id", sa.text("snapshot_date DESC")],
    )
    op.create_index(
        "idx_tenant_llm_daily_date",
        "tenant_llm_daily_snapshots",
        ["snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_tenant_llm_daily_date",
        table_name="tenant_llm_daily_snapshots",
    )
    op.drop_index(
        "idx_tenant_llm_daily_tenant_date_desc",
        table_name="tenant_llm_daily_snapshots",
    )
    op.drop_table("tenant_llm_daily_snapshots")
