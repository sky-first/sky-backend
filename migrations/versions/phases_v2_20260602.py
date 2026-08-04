"""Extend provisioning_job_events.phase CHECK constraint.

The original constraint allowed only the onboard phases that existed
when the table was created (preflight/plan/gitops/namespaces/secrets/
bootstrap/smoke/report). Two new things need to fit:

1. ``ingress`` — added to the onboard workflow shortly after PR #476
   to wire the per-tenant subdomain. The model has the phase but the
   DB constraint never grew, so INSERTs silently 422'd against the
   webhook and the Console missed the row.
2. ``cluster`` and ``data`` — the offboard workflow's phase names.
   The Celery reconciler (PR #506) now synthesizes events from the
   GitHub Actions Jobs API as a backstop for lossy webhooks; without
   this migration those INSERTs would CHECK-fail for any offboard.

This is a constraint replacement only, no row writes. Drop + recreate
is the standard pattern for ALTER CHECK in PostgreSQL.

Revision ID: phases_v2_20260602
Revises: messages_user_id_20260602
Create Date: 2026-06-02

Note: original revision id was ``provisioning_phases_extend_20260602``
(35 chars) — overflowed the shared ``alembic_version_be.version_num
VARCHAR(32)`` column and broke ``alembic upgrade head`` for every
migrate Job. Renamed to ``phases_v2_20260602`` (18 chars). Safe to
rename because no alembic_version table ever stored the old value —
every migrate attempt rolled back the transaction when the UPDATE
failed at the very end of the upgrade.
"""

from __future__ import annotations

from alembic import op


revision = "phases_v2_20260602"
down_revision = "messages_user_id_20260602"
branch_labels = None
depends_on = None


# Authoritative set of phase names the BE accepts. Mirrors
# ``src.models.internal_console.PROVISIONING_PHASES`` plus the
# offboard-only phases (``cluster``, ``data``) — kept in sync there.
ALLOWED_PHASES_V2 = (
    # onboard
    "preflight",
    "plan",
    "gitops",
    "namespaces",
    "secrets",
    "bootstrap",
    "ingress",
    "smoke",
    "report",
    # offboard
    "cluster",
    "data",
)


def _phase_check_expr(phases: tuple[str, ...]) -> str:
    return "phase IN (" + ", ".join(f"'{p}'" for p in phases) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite test suite tolerates CHECK changes via batch_alter;
        # the test conftest builds the table fresh anyway, so a no-op
        # here keeps the tests happy without rewriting the constraint.
        return

    # Postgres: drop the old CHECK, install the new one.
    op.drop_constraint(
        "provisioning_job_events_phase_check",
        "provisioning_job_events",
        type_="check",
    )
    op.create_check_constraint(
        "provisioning_job_events_phase_check",
        "provisioning_job_events",
        _phase_check_expr(ALLOWED_PHASES_V2),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    # Roll back to the original onboard-only allow-list. Note this
    # would CHECK-fail any rows we synthesized for ingress/cluster/
    # data in the meantime — operator must accept that on downgrade.
    op.drop_constraint(
        "provisioning_job_events_phase_check",
        "provisioning_job_events",
        type_="check",
    )
    op.create_check_constraint(
        "provisioning_job_events_phase_check",
        "provisioning_job_events",
        "phase IN ('preflight','plan','gitops','namespaces','secrets',"
        "'bootstrap','smoke','report')",
    )
