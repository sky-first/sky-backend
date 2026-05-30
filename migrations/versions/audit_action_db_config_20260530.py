"""Audit action enum — add ``update_db_config`` + ``test_db_config``.

Backs the Console "Database" tab (PR #19) where Sky-team operators
edit a tenant's data-plane connection details (``db_host``,
``db_credentials_secret_arn``, …) and run a connectivity test before
saving. Both actions need their own audit-log enum values so we can
filter on them later and so the existing CHECK constraint doesn't
reject the row at INSERT time.

The migration drops the old CHECK constraint and re-creates it with
the two extra values appended. On SQLite (test suite) we no-op — the
constraint is enforced via Python by the SQLAlchemy ``CheckConstraint``
declaration on the model, which re-runs against ``Base.metadata`` when
the in-memory schema is created.

Revision ID: audit_action_db_config_20260530
Revises: provisioning_events_20260530
Create Date: 2026-05-30
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "audit_action_db_config_20260530"
down_revision = "provisioning_events_20260530"
branch_labels = None
depends_on = None


_OLD_VALUES = (
    "view_tenant",
    "view_audit",
    "view_dashboard",
    "create_tenant",
    "update_tenant",
    "suspend_tenant",
    "resume_tenant",
    "destroy_tenant",
    "change_tier",
    "update_capacity",
    "grant_role",
    "revoke_role",
)

_NEW_VALUES = _OLD_VALUES + ("update_db_config", "test_db_config")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite enforces CHECKs at create_all time; nothing to ALTER.
        return

    if not inspect(bind).has_table("internal_console_audit"):
        return

    op.execute(
        "ALTER TABLE internal_console_audit "
        "DROP CONSTRAINT IF EXISTS internal_console_audit_action_check"
    )
    op.execute(
        "ALTER TABLE internal_console_audit "
        "ADD CONSTRAINT internal_console_audit_action_check "
        f"CHECK (action IN ({_quoted(_NEW_VALUES)}))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    if not inspect(bind).has_table("internal_console_audit"):
        return

    # Rows written under the new enum values would block the constraint
    # re-creation; clear them first. Audit is append-only in production
    # but this is operator-initiated rollback.
    op.execute(
        "DELETE FROM internal_console_audit "
        "WHERE action IN ('update_db_config', 'test_db_config')"
    )
    op.execute(
        "ALTER TABLE internal_console_audit "
        "DROP CONSTRAINT IF EXISTS internal_console_audit_action_check"
    )
    op.execute(
        "ALTER TABLE internal_console_audit "
        "ADD CONSTRAINT internal_console_audit_action_check "
        f"CHECK (action IN ({_quoted(_OLD_VALUES)}))"
    )
