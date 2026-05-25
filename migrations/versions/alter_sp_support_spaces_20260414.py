"""Service principals can now be owned by a space OR a crew.

Today `service_principals` has a UNIQUE `crew_id` (one SP per crew, created
automatically on crew creation). Collaborative agents also need an SP per
space so page-level agents in a space have a stable identity independent of
any specific crew.

This migration:
  1. Adds a nullable `space_id` column with a unique constraint.
  2. Relaxes `crew_id NOT NULL` → nullable.
  3. Adds a check constraint: exactly one of `crew_id` / `space_id` is set.
  4. Backfills a service principal for every pre-existing space.

Downgrade re-tightens `crew_id NOT NULL` after first deleting any space-only
rows (they could not be represented in the old schema anyway).

Revision ID: sp_spaces_20260414
Revises: widgets_agent_refs_20260414
Create Date: 2026-04-14 14:10:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "sp_spaces_20260414"
down_revision = "widgets_agent_refs_20260414"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add space_id column (nullable for now; constraint added below)
    op.add_column(
        "service_principals",
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_service_principals_space_id",
        "service_principals",
        ["space_id"],
    )

    # 2. Allow crew_id to be NULL so space-only rows are valid
    op.alter_column("service_principals", "crew_id", nullable=True)

    # 3. Enforce exactly-one invariant at the DB level
    op.create_check_constraint(
        "ck_service_principals_owner_exactly_one",
        "service_principals",
        "(crew_id IS NOT NULL) <> (space_id IS NOT NULL)",
    )

    # 4. Backfill a service principal for every existing space that does not
    #    already have one.
    op.execute(
        """
        INSERT INTO service_principals (id, space_id, name, active, created_at)
        SELECT
            gen_random_uuid(),
            s.id,
            'sa-space-' || substring(s.id::text from 1 for 8),
            true,
            COALESCE(s.created_at, NOW())
        FROM spaces s
        WHERE NOT EXISTS (
            SELECT 1 FROM service_principals sp WHERE sp.space_id = s.id
        )
        """
    )


def downgrade() -> None:
    # Drop constraints first so we can delete rows freely.
    op.drop_constraint(
        "ck_service_principals_owner_exactly_one",
        "service_principals",
        type_="check",
    )

    # Remove any space-only rows — they have no crew_id and cannot survive the
    # reinstated NOT NULL on crew_id.
    op.execute("DELETE FROM service_principals WHERE space_id IS NOT NULL")

    op.drop_constraint(
        "uq_service_principals_space_id",
        "service_principals",
        type_="unique",
    )
    op.drop_column("service_principals", "space_id")
    op.alter_column("service_principals", "crew_id", nullable=False)
