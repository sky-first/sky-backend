"""Password-reset columns on users (forgot-password / reset-password).

Phase: self-service password recovery for tenants that allow password
auth (SSO-only tenants never use these). Two nullable columns added to
``users``, mirroring the existing invite-token columns:

* ``password_reset_token``      — urlsafe token minted by
  ``POST /auth/forgot-password``. Cleared the moment
  ``POST /auth/reset-password`` consumes it (or once it expires). A
  partial index keyed on the non-null token speeds the reset lookup
  without bloating the index with the (overwhelmingly null) common case.
* ``password_reset_expires_at`` — UTC expiry for the token (the endpoint
  sets a 1-hour window). NULL when no reset is in flight.

Both columns are nullable with no server default, so the migration is
additive and zero-impact on existing rows — no backfill required.

NOTE: sky-be and sky-ai share one database and one ``alembic_version``
table, so this revision chains onto the current head of THIS repo's
migration chain (``notif_i18n_keys_20260612``). Keep additive + reversible
so a cross-app head move never strands it.

Revision ID: password_reset_cols_20260614
Revises: notif_i18n_keys_20260612
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "password_reset_cols_20260614"
down_revision = "notif_i18n_keys_20260612"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "password_reset_token",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "password_reset_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    # Partial index — mirrors idx_users_invite_token. Only the rows with a
    # reset in flight are indexed, so the reset-token lookup is fast and the
    # index stays tiny.
    op.create_index(
        "idx_users_password_reset_token",
        "users",
        ["password_reset_token"],
        unique=False,
        postgresql_where=sa.text("password_reset_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_password_reset_token", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_reset_expires_at")
        batch.drop_column("password_reset_token")
