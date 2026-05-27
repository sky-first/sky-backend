"""Internal Console tables — audit log + provisioning jobs (Projeto B PR B#1).

Two tables that back the Sky-team admin Console:

* ``internal_console_audit`` — append-only log of every action taken
  through the console (reads + writes). Indexed by tenant and by
  actor so the detail view can pull a tenant-scoped feed cheaply and
  the audit screen can answer "what did Lucas do last week".
* ``provisioning_jobs`` — long-running async jobs spawned by Create /
  Suspend / Resume / Destroy. The console polls this table (and a
  WebSocket on top of it later) to surface per-phase progress without
  blocking the HTTP request that kicked the job off.

Neither table touches ``tenant_registry`` — the registry stays the
source of truth for tenant config; this migration only adds the
operational scaffolding around it.

Revision ID: internal_console_20260527
Revises: tenant_registry_20260526
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID

revision = "internal_console_20260527"
down_revision = "tenant_registry_20260526"
branch_labels = None
depends_on = None


# Mirrors ``AuditAction`` in src/models/internal_console.py — kept literal
# for the migration to remain self-contained.
ALLOWED_ACTIONS = (
    # reads
    "view_tenant",
    "view_audit",
    "view_dashboard",
    # writes — lifecycle
    "create_tenant",
    "update_tenant",
    "suspend_tenant",
    "resume_tenant",
    "destroy_tenant",
    "change_tier",
    "update_capacity",
    # writes — auth / RBAC
    "grant_role",
    "revoke_role",
)

ALLOWED_RESULTS = ("success", "failure", "partial")

ALLOWED_JOB_TYPES = (
    "create",
    "suspend",
    "resume",
    "destroy",
    "tier_change",
)

ALLOWED_JOB_STATUSES = (
    "pending",
    "running",
    "success",
    "failed",
    "cancelled",
)

_JSONB_OR_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
_INET_OR_TEXT = INET().with_variant(sa.String(length=45), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── internal_console_audit ──────────────────────────────────────
    if not inspector.has_table("internal_console_audit"):
        op.create_table(
            "internal_console_audit",
            sa.Column(
                "id",
                PG_UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("actor_ip", _INET_OR_TEXT, nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("tenant_slug", sa.String(length=50), nullable=True),
            sa.Column("request_payload", _JSONB_OR_JSON, nullable=True),
            sa.Column("result", sa.String(length=20), nullable=False),
            sa.Column("result_details", _JSONB_OR_JSON, nullable=True),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                f"action IN {ALLOWED_ACTIONS}",
                name="internal_console_audit_action_check",
            ),
            sa.CheckConstraint(
                f"result IN {ALLOWED_RESULTS}",
                name="internal_console_audit_result_check",
            ),
        )
        op.create_index(
            "idx_console_audit_tenant",
            "internal_console_audit",
            ["tenant_slug", "timestamp"],
        )
        op.create_index(
            "idx_console_audit_actor",
            "internal_console_audit",
            ["actor_email", "timestamp"],
        )
        op.create_index(
            "idx_console_audit_action",
            "internal_console_audit",
            ["action", "timestamp"],
        )

    # ── provisioning_jobs ──────────────────────────────────────────
    if not inspector.has_table("provisioning_jobs"):
        op.create_table(
            "provisioning_jobs",
            sa.Column(
                "id",
                PG_UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_slug", sa.String(length=50), nullable=False),
            sa.Column("actor_email", sa.String(length=255), nullable=False),
            sa.Column("job_type", sa.String(length=50), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("output", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("request_payload", _JSONB_OR_JSON, nullable=True),
            sa.CheckConstraint(
                f"job_type IN {ALLOWED_JOB_TYPES}",
                name="provisioning_jobs_type_check",
            ),
            sa.CheckConstraint(
                f"status IN {ALLOWED_JOB_STATUSES}",
                name="provisioning_jobs_status_check",
            ),
        )
        op.create_index(
            "idx_provisioning_tenant",
            "provisioning_jobs",
            ["tenant_slug", "started_at"],
        )
        op.create_index(
            "idx_provisioning_status",
            "provisioning_jobs",
            ["status", "started_at"],
        )


def downgrade() -> None:
    op.drop_index("idx_provisioning_status", table_name="provisioning_jobs")
    op.drop_index("idx_provisioning_tenant", table_name="provisioning_jobs")
    op.drop_table("provisioning_jobs")
    op.drop_index("idx_console_audit_action", table_name="internal_console_audit")
    op.drop_index("idx_console_audit_actor", table_name="internal_console_audit")
    op.drop_index("idx_console_audit_tenant", table_name="internal_console_audit")
    op.drop_table("internal_console_audit")
