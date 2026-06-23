"""Add 'manually_completed' to provisioning_jobs.status CHECK constraint.

Operators can now mark a tenant as operationally healthy even when the
underlying GH Actions run failed — useful when the failure was a
cosmetic webhook timeout (e.g. the migrate Job took longer than the
workflow wait but the alembic upgrade itself succeeded) and the
remaining phases were re-applied by hand.

Revision ID: manually_completed_20260603
Revises: phases_v2_20260602
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op


revision = "manually_completed_20260603"
down_revision = "phases_v2_20260602"
branch_labels = None
depends_on = None


_OLD = "status IN ('pending', 'running', 'success', 'failed', 'cancelled')"
_NEW = (
    "status IN ('pending', 'running', 'success', 'failed', "
    "'cancelled', 'manually_completed')"
)


def upgrade() -> None:
    op.drop_constraint(
        "provisioning_jobs_status_check",
        "provisioning_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "provisioning_jobs_status_check",
        "provisioning_jobs",
        _NEW,
    )


def downgrade() -> None:
    op.drop_constraint(
        "provisioning_jobs_status_check",
        "provisioning_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "provisioning_jobs_status_check",
        "provisioning_jobs",
        _OLD,
    )
