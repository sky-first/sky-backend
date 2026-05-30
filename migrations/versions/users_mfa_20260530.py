"""Multi-Factor Authentication (TOTP) columns on users (Phase 3).

Phase 3 of the auth roadmap layers RFC 6238 time-based one-time
passwords (TOTP) over the existing local-password and SSO flows.
Enrolment is opt-in for tenant users; the Console-side guard for
Sky-team operators (``CONSOLE_REQUIRE_MFA``) starts disabled and is
toggled on per-environment once the rollout is complete.

Columns added to ``users``:

* ``mfa_enabled``                — quick boolean used by the login
  flow to decide whether to issue a real access token or an MFA
  challenge token. False on every existing row so the migration is
  zero-impact at deploy time.
* ``mfa_secret_encrypted``       — Fernet-encrypted base32 TOTP
  secret. Encryption uses the same ENCRYPTION_KEY env var as
  connection credentials so we don't add a new key to KMS.
* ``mfa_recovery_codes_encrypted`` — Fernet-encrypted JSON list of
  10 bcrypt hashes (one per backup code). The plaintext codes are
  shown once at enrolment time only; from then on we only ever
  verify a presented code against the stored hashes and mark the
  matching slot as ``used``.
* ``mfa_enrolled_at``            — audit timestamp set when
  ``verify_enrollment`` flips ``mfa_enabled`` true.
* ``mfa_last_used_at``           — last successful TOTP or recovery
  consumption. Helps the Console flag dormant 2FA setups.

All five columns are nullable / default-false; no backfill is needed.
``mfa_enabled`` defaults to false at the column level so legacy auth0
SSO callbacks that bypass the SQLAlchemy default still land on the
right value.

Revision ID: users_mfa_20260530
Revises: provisioning_events_20260530
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "users_mfa_20260530"
down_revision = "provisioning_events_20260530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "mfa_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(
            sa.Column(
                "mfa_secret_encrypted",
                sa.LargeBinary(),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "mfa_recovery_codes_encrypted",
                sa.LargeBinary(),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "mfa_enrolled_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "mfa_last_used_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("mfa_last_used_at")
        batch.drop_column("mfa_enrolled_at")
        batch.drop_column("mfa_recovery_codes_encrypted")
        batch.drop_column("mfa_secret_encrypted")
        batch.drop_column("mfa_enabled")
