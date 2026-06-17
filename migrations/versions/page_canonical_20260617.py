"""canonical page per crew/space — is_canonical flag + unique indexes + backfill

Enforces "exactly ONE canonical page per crew (and per space-level scope)".
The canonical page is the shared room every member converges on so live
cursors/websockets work. Steps:
  1. Add pages.is_canonical (bool, default false).
  2. Backfill: elect the OLDEST page per crew (and per space-level group) as
     canonical, and rename legacy "Team Canvas" crew pages to "<crew> Page".
  3. Partial unique indexes guaranteeing at most one canonical per crew/space.

Idempotent: safe to re-run (guards on column/index existence).

Revision ID: page_canonical_20260617
Revises: crew_tables_20260615
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "page_canonical_20260617"
down_revision = "crew_tables_20260615"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pages" not in inspector.get_table_names():
        return

    columns = [c["name"] for c in inspector.get_columns("pages")]
    if "is_canonical" not in columns:
        op.add_column(
            "pages",
            sa.Column(
                "is_canonical",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # ── Backfill — Postgres only (raw window functions). On SQLite (tests)
    #    the column default is enough; the suite seeds its own data.
    if bind.dialect.name == "postgresql":
        # 1) Elect the oldest page per crew as canonical.
        op.execute(
            sa.text(
                """
                WITH ranked AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY crew_id
                               ORDER BY created_at ASC, id ASC
                           ) AS rn
                    FROM pages
                    WHERE crew_id IS NOT NULL AND deleted_at IS NULL
                )
                UPDATE pages p
                SET is_canonical = true
                FROM ranked r
                WHERE p.id = r.id AND r.rn = 1
                """
            )
        )
        # 2) Rename legacy "Team Canvas" canonical crew pages to "<crew> Page".
        op.execute(
            sa.text(
                """
                UPDATE pages p
                SET name = btrim(c.name) || ' Page'
                FROM crews c
                WHERE p.crew_id = c.id
                  AND p.is_canonical = true
                  AND p.deleted_at IS NULL
                  AND (p.name IS NULL OR btrim(p.name) IN ('', 'Team Canvas'))
                  AND c.name IS NOT NULL AND btrim(c.name) <> ''
                """
            )
        )
        # 3) Elect the oldest space-level page (no crew) per space as canonical.
        op.execute(
            sa.text(
                """
                WITH ranked AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY space_id
                               ORDER BY created_at ASC, id ASC
                           ) AS rn
                    FROM pages
                    WHERE space_id IS NOT NULL
                      AND crew_id IS NULL
                      AND deleted_at IS NULL
                )
                UPDATE pages p
                SET is_canonical = true
                FROM ranked r
                WHERE p.id = r.id AND r.rn = 1
                """
            )
        )

    # ── Partial unique indexes: at most one canonical per crew / per space.
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("pages")}
    if bind.dialect.name == "postgresql":
        if "uq_pages_canonical_crew" not in existing_indexes:
            op.execute(
                sa.text(
                    """
                    CREATE UNIQUE INDEX uq_pages_canonical_crew
                    ON pages (crew_id)
                    WHERE is_canonical AND crew_id IS NOT NULL AND deleted_at IS NULL
                    """
                )
            )
        if "uq_pages_canonical_space" not in existing_indexes:
            op.execute(
                sa.text(
                    """
                    CREATE UNIQUE INDEX uq_pages_canonical_space
                    ON pages (space_id)
                    WHERE is_canonical AND space_id IS NOT NULL
                      AND crew_id IS NULL AND deleted_at IS NULL
                    """
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pages" not in inspector.get_table_names():
        return
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("pages")}
    if "uq_pages_canonical_crew" in existing_indexes:
        op.drop_index("uq_pages_canonical_crew", table_name="pages")
    if "uq_pages_canonical_space" in existing_indexes:
        op.drop_index("uq_pages_canonical_space", table_name="pages")
    columns = [c["name"] for c in inspector.get_columns("pages")]
    if "is_canonical" in columns:
        op.drop_column("pages", "is_canonical")
