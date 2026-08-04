"""Seed the SkyFirst engineering team as Console operators.

Marks the canonical Sky engineering accounts with
``users.is_sky_operator = true`` so they can sign in to the Internal
Console without an out-of-band SQL update. Idempotent — re-running
only flips users that are currently false.

The list is kept small on purpose: production marks people here as
they join the team. Casual contributors keep ``is_sky_operator =
false`` and are granted Console access via ``CONSOLE_ALLOWED_EMAILS``
env if needed.

Revision ID: seed_sky_operators_20260529
Revises: tenant_auth_methods_20260529
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "seed_sky_operators_20260529"
down_revision = "tenant_auth_methods_20260529"
branch_labels = None
depends_on = None


# Canonical Sky-team emails. Add here when a new operator joins.
SKY_OPERATORS = (
    "lucas.ventura@skyfirstlabs.com",
    "gustavo.mendonca@skyfirstlabs.com",
    "paulo.bomfim@skyfirstlabs.com",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_sky_operator" not in cols or "email" not in cols:
        return

    # Single UPDATE flips any matching rows that are currently false.
    # No INSERT — the migration must not create users out of nowhere;
    # if the email is not yet in the system the operator signs in via
    # SSO first and the next ``alembic upgrade`` picks them up.
    op.execute(
        sa.text(
            "UPDATE users "
            "SET is_sky_operator = true "
            "WHERE LOWER(email) = ANY(:emails) "
            "AND is_sky_operator = false"
        ).bindparams(
            sa.bindparam(
                "emails",
                [e.lower() for e in SKY_OPERATORS],
                type_=sa.ARRAY(sa.String()),
            )
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_sky_operator" not in cols or "email" not in cols:
        return
    op.execute(
        sa.text(
            "UPDATE users "
            "SET is_sky_operator = false "
            "WHERE LOWER(email) = ANY(:emails)"
        ).bindparams(
            sa.bindparam(
                "emails",
                [e.lower() for e in SKY_OPERATORS],
                type_=sa.ARRAY(sa.String()),
            )
        )
    )
