"""Sky-platform role hierarchy (ceo / admin / support / read_only).

The Console gates features by this value, independent from the
tenant-side ``users.role`` (owner / admin / member). Null for
customer users; populated only when ``is_sky_operator`` is True. The
migration seeds the three founders so the Console reads CEO / Admin
out of the box instead of bottoming out at ``read_only``.

Revision ID: sky_role_20260529
Revises: seed_sky_operators_20260529
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "sky_role_20260529"
down_revision = "seed_sky_operators_20260529"
branch_labels = None
depends_on = None


_CEO_EMAIL = "lucas.ventura@skyfirstlabs.com"
_ADMIN_EMAILS = (
    "gustavo.mendonca@skyfirstlabs.com",
    "paulo.bomfim@skyfirstlabs.com",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "sky_role" not in cols:
        op.add_column(
            "users",
            sa.Column("sky_role", sa.String(length=20), nullable=True),
        )
        cols = cols | {"sky_role"}

    # NOTE 2026-05-29: ``ceo`` was the original seed label here; the
    # follow-up rename migration ``sky_role_rename_ceo_to_owner_…``
    # turns any lingering ``ceo`` rows into ``owner``. Updating this
    # script in-place would risk a re-run on an already-upgraded DB,
    # so we leave the historical seed alone and rely on the rename.
    op.execute(
        sa.text(
            "UPDATE users "
            "SET sky_role = 'ceo' "
            "WHERE LOWER(email) = :email "
            "AND (sky_role IS NULL OR sky_role = 'read_only')"
        ).bindparams(email=_CEO_EMAIL)
    )
    op.execute(
        sa.text(
            "UPDATE users "
            "SET sky_role = 'admin' "
            "WHERE LOWER(email) = ANY(:emails) "
            "AND (sky_role IS NULL OR sky_role = 'read_only')"
        ).bindparams(
            sa.bindparam(
                "emails",
                [e.lower() for e in _ADMIN_EMAILS],
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
    if "sky_role" in cols:
        op.drop_column("users", "sky_role")
