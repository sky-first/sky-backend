"""Provisioning workflow engine — events table + new columns on jobs.

Adds the data plumbing the Console UI needs to render the live
"provisioning timeline" for a tenant being created. The Console
already produced ``provisioning_jobs`` rows but had no way to
observe the actual phases of the underlying GitOps workflow; this
migration adds:

1. Three columns on ``provisioning_jobs``:
   * ``current_phase`` — last phase reported as ``succeeded`` (advances
     monotonically through the canonical sequence).
   * ``external_run_id`` — GitHub Actions ``run_id`` we dispatched.
   * ``external_run_url`` — full ``actions/runs/<id>`` URL for deep-link.
2. ``provisioning_job_events`` — append-only event log written by the
   workflow itself via signed webhook. One row per phase transition.

The events table is intentionally separate from the jobs table so we
can stream/replay without contending with the row that the
``current_phase`` update lives on.

Revision ID: provisioning_events_20260530
Revises: rename_pilot_to_starter_20260530
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "provisioning_events_20260530"
down_revision = "rename_pilot_to_starter_20260530"
branch_labels = None
depends_on = None


# Keep the canonical phase tuple here as the source of truth for the
# CHECK constraint. ``src.models.internal_console.PROVISIONING_PHASES``
# mirrors this; any change to either must update both.
ALLOWED_PHASES = (
    "preflight",
    "plan",
    "gitops",
    "namespaces",
    "secrets",
    "bootstrap",
    "smoke",
    "report",
)
ALLOWED_STATUSES = ("started", "succeeded", "failed")
ALLOWED_LEVELS = ("info", "warning", "error")


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _jsonb() -> sa.types.TypeEngine:
    """JSONB on Postgres, plain JSON on SQLite (test suite)."""
    return JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # 1) ALTER provisioning_jobs — three nullable columns. None of the
    #    existing rows need backfill: ``current_phase`` is allowed NULL
    #    while a job is still queued, and the two ``external_*`` fields
    #    only populate once the Celery task dispatches the workflow.
    with op.batch_alter_table("provisioning_jobs") as batch:
        batch.add_column(sa.Column("current_phase", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("external_run_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("external_run_url", sa.Text(), nullable=True))

    # 2) CREATE provisioning_job_events. Indexed on (job_id, created_at)
    #    so the SSE replay path can do a tight range-scan.
    op.create_table(
        "provisioning_job_events",
        sa.Column("id", UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
                  primary_key=True),
        sa.Column(
            "job_id",
            UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
            sa.ForeignKey("provisioning_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "level",
            sa.String(length=20),
            nullable=False,
            server_default="info",
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "event_metadata",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "phase IN ("
            + ", ".join(f"'{p}'" for p in ALLOWED_PHASES)
            + ")",
            name="provisioning_job_events_phase_check",
        ),
        sa.CheckConstraint(
            "status IN ("
            + ", ".join(f"'{s}'" for s in ALLOWED_STATUSES)
            + ")",
            name="provisioning_job_events_status_check",
        ),
        sa.CheckConstraint(
            "level IN ("
            + ", ".join(f"'{l}'" for l in ALLOWED_LEVELS)
            + ")",
            name="provisioning_job_events_level_check",
        ),
    )
    op.create_index(
        "idx_provisioning_job_events_job_created",
        "provisioning_job_events",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_provisioning_job_events_job_created",
        table_name="provisioning_job_events",
    )
    op.drop_table("provisioning_job_events")

    with op.batch_alter_table("provisioning_jobs") as batch:
        batch.drop_column("external_run_url")
        batch.drop_column("external_run_id")
        batch.drop_column("current_phase")
