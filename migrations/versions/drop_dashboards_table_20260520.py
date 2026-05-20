"""Drop dashboards table, consolidate into pages.

Lucas's call (2026-05-20): pages and dashboards have been semantically
1:1 since day one (every page has exactly one dashboard, we never
shipped tabbed multi-dashboard pages). The duplicate concept added
nothing but confusion and three layers of FK indirection on every
widget/comment/connection query. This migration collapses them into
one — "page" is the single canonical container.

Clean cut, no expand-contract. After this migration:
- ``dashboards`` table is gone
- Widget / Connection / Comment / DashboardBuildJob now reference
  ``page_id`` directly
- Page absorbs ``canvas_settings``, ``is_locked``, ``template_id``
  from the dropped Dashboard
- ``DashboardBuildJob`` renamed to ``PageBuildJob``

Sequence inside the migration (single transaction):
1. Add new pages columns: canvas_settings, is_locked, template_id
2. Add page_id (NULL) on widgets, widget_connections, comments,
   dashboard_build_jobs
3. Backfill page_id from dashboards.page_id via dashboard_id
4. Backfill new pages columns from the dashboard rows (DISTINCT ON
   to pick deterministically when a page has >1 dashboard)
5. Drop dashboard_id columns + their FK/indexes
6. Drop dashboards table
7. Rename dashboard_build_jobs → page_build_jobs

Revision ID: drop_dashboards_table_20260520
Revises: agent_finding_viz_kind_20260515
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "drop_dashboards_table_20260520"
down_revision = "agent_finding_viz_kind_20260515"
branch_labels = None
depends_on = None


# ─── helpers ────────────────────────────────────────────────────────────────


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector, table: str, index_name: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(i["name"] == index_name for i in inspector.get_indexes(table))


def _has_fk(inspector, table: str, fk_name: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table))


def _find_fk_by_column(inspector, table: str, column: str) -> str | None:
    """Return FK constraint name for a given column (PG generates one
    if alembic didn't name it explicitly)."""
    if not inspector.has_table(table):
        return None
    for fk in inspector.get_foreign_keys(table):
        if column in fk.get("constrained_columns", []):
            return fk["name"]
    return None


# ─── upgrade ────────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("pages"):
        # Bare DB, nothing to migrate
        return

    # ─── 1. ADD COLUMNS ON pages ────────────────────────────────────────────

    if not _has_column(inspector, "pages", "canvas_settings"):
        op.add_column(
            "pages",
            sa.Column("canvas_settings", sa.JSON(), nullable=True),
        )
    if not _has_column(inspector, "pages", "is_locked"):
        op.add_column(
            "pages",
            sa.Column(
                "is_locked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column(inspector, "pages", "template_id"):
        op.add_column(
            "pages",
            sa.Column(
                "template_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        if inspector.has_table("templates"):
            op.create_foreign_key(
                "fk_pages_template_id",
                "pages",
                "templates",
                ["template_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ─── 2. ADD page_id ON DEPENDENT TABLES ─────────────────────────────────

    dependent_tables = [
        "widgets",
        "widget_connections",
        "comments",
        "dashboard_build_jobs",
    ]
    for table in dependent_tables:
        if inspector.has_table(table) and not _has_column(inspector, table, "page_id"):
            op.add_column(
                table,
                sa.Column(
                    "page_id",
                    sa.dialects.postgresql.UUID(as_uuid=True),
                    nullable=True,
                ),
            )

    # Refresh inspector after column adds (some metadata cached)
    inspector = sa.inspect(bind)

    # ─── 3 & 4. BACKFILL (only if legacy dashboards is still here) ──────────

    if inspector.has_table("dashboards"):
        for table in dependent_tables:
            if _has_column(inspector, table, "dashboard_id") and _has_column(
                inspector, table, "page_id"
            ):
                op.execute(
                    sa.text(
                        f"""
                        UPDATE {table} AS t
                        SET page_id = d.page_id
                        FROM dashboards AS d
                        WHERE t.dashboard_id = d.id
                          AND t.page_id IS NULL
                        """
                    )
                )

        # Backfill page canvas settings from the most recent live dashboard
        # per page (DISTINCT ON guarantees determinism when a page has >1)
        op.execute(
            sa.text(
                """
                UPDATE pages AS p
                SET canvas_settings = d.canvas_settings,
                    is_locked       = COALESCE(d.is_locked, false),
                    template_id     = d.template_id
                FROM (
                    SELECT DISTINCT ON (page_id)
                        page_id, canvas_settings, is_locked, template_id
                    FROM dashboards
                    WHERE deleted_at IS NULL
                    ORDER BY page_id, created_at DESC
                ) AS d
                WHERE p.id = d.page_id
                  AND p.canvas_settings IS NULL
                """
            )
        )

        # Safety net: rows that didn't backfill (FK pointing at deleted
        # dashboards) get deleted — they're orphans by definition.
        for table in dependent_tables:
            if _has_column(inspector, table, "page_id"):
                op.execute(sa.text(f"DELETE FROM {table} WHERE page_id IS NULL"))

    # ─── 5. ENFORCE page_id NOT NULL + FK + INDEX ───────────────────────────

    for table in dependent_tables:
        if not _has_column(inspector, table, "page_id"):
            continue
        op.alter_column(table, "page_id", nullable=False)
        fk_name = f"fk_{table}_page_id"
        if not _has_fk(inspector, table, fk_name):
            op.create_foreign_key(
                fk_name,
                table,
                "pages",
                ["page_id"],
                ["id"],
                ondelete="CASCADE",
            )
        idx_name = f"idx_{table}_page_id"
        if not _has_index(inspector, table, idx_name):
            op.create_index(idx_name, table, ["page_id"])

    # ─── 6. DROP dashboard_id COLUMNS (with FKs + indexes) ──────────────────

    for table in dependent_tables:
        if not _has_column(inspector, table, "dashboard_id"):
            continue
        # Drop named FK if alembic created one (legacy names)
        for fk_candidate in (
            f"fk_{table}_dashboard_id",
            f"{table}_dashboard_id_fkey",
        ):
            if _has_fk(inspector, table, fk_candidate):
                try:
                    op.drop_constraint(fk_candidate, table, type_="foreignkey")
                except Exception:
                    pass
        # Fallback: look up the FK by column
        fk_name = _find_fk_by_column(inspector, table, "dashboard_id")
        if fk_name:
            try:
                op.drop_constraint(fk_name, table, type_="foreignkey")
            except Exception:
                pass
        # Drop indexes referencing dashboard_id
        for idx_candidate in (
            f"idx_{table}_dashboard_id",
            f"{table}_dashboard_id_idx",
        ):
            if _has_index(inspector, table, idx_candidate):
                try:
                    op.drop_index(idx_candidate, table_name=table)
                except Exception:
                    pass
        op.drop_column(table, "dashboard_id")

    # ─── 7. DROP dashboards TABLE ───────────────────────────────────────────

    if inspector.has_table("dashboards"):
        op.drop_table("dashboards")

    # ─── 8. RENAME dashboard_build_jobs → page_build_jobs ───────────────────

    inspector = sa.inspect(bind)
    if inspector.has_table("dashboard_build_jobs") and not inspector.has_table(
        "page_build_jobs"
    ):
        op.rename_table("dashboard_build_jobs", "page_build_jobs")
        # Rename associated indexes for clarity (best effort)
        for old_idx, new_idx in (
            ("idx_dashboard_build_jobs_page_id", "idx_page_build_jobs_page_id"),
            ("idx_dashboard_build_jobs_status", "idx_page_build_jobs_status"),
            ("idx_dashboard_build_jobs_created_at", "idx_page_build_jobs_created_at"),
        ):
            try:
                op.execute(sa.text(f"ALTER INDEX IF EXISTS {old_idx} RENAME TO {new_idx}"))
            except Exception:
                pass
        # Rename the FK we just created (it was fk_dashboard_build_jobs_page_id)
        try:
            op.execute(
                sa.text(
                    """
                    ALTER TABLE page_build_jobs
                    RENAME CONSTRAINT fk_dashboard_build_jobs_page_id
                    TO fk_page_build_jobs_page_id
                    """
                )
            )
        except Exception:
            pass


# ─── downgrade ──────────────────────────────────────────────────────────────


def downgrade() -> None:
    """Best-effort downgrade. Cannot recover the original ``dashboards.id``
    values that other systems may have referenced — recreates one
    dashboard row per page with fresh UUIDs. URLs and audit logs that
    referenced the old dashboard IDs will be broken.

    If you need a real rollback path, restore from a pre-migration
    database snapshot.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Rename page_build_jobs back to dashboard_build_jobs
    if inspector.has_table("page_build_jobs") and not inspector.has_table(
        "dashboard_build_jobs"
    ):
        op.rename_table("page_build_jobs", "dashboard_build_jobs")

    # Recreate dashboards table with the canvas fields
    if not inspector.has_table("dashboards"):
        op.create_table(
            "dashboards",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "page_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("pages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "template_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("templates.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("canvas_settings", sa.JSON, nullable=True),
            sa.Column(
                "is_locked",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_by",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

        # Seed one dashboard per page
        op.execute(
            sa.text(
                """
                INSERT INTO dashboards (id, name, page_id, canvas_settings, is_locked, template_id, created_at, updated_at)
                SELECT gen_random_uuid(), p.name, p.id, p.canvas_settings, p.is_locked, p.template_id, NOW(), NOW()
                FROM pages p
                WHERE p.deleted_at IS NULL
                """
            )
        )

    # Recreate dashboard_id columns on dependent tables and backfill from
    # the new dashboard rows.
    dependent_tables = [
        "widgets",
        "widget_connections",
        "comments",
        "dashboard_build_jobs",
    ]
    inspector = sa.inspect(bind)
    for table in dependent_tables:
        if inspector.has_table(table) and not _has_column(inspector, table, "dashboard_id"):
            op.add_column(
                table,
                sa.Column(
                    "dashboard_id",
                    sa.dialects.postgresql.UUID(as_uuid=True),
                    nullable=True,
                ),
            )
            op.execute(
                sa.text(
                    f"""
                    UPDATE {table} AS t
                    SET dashboard_id = d.id
                    FROM dashboards AS d
                    WHERE d.page_id = t.page_id
                    """
                )
            )
            op.alter_column(table, "dashboard_id", nullable=False)
            op.create_foreign_key(
                f"fk_{table}_dashboard_id",
                table,
                "dashboards",
                ["dashboard_id"],
                ["id"],
                ondelete="CASCADE",
            )
            op.create_index(f"idx_{table}_dashboard_id", table, ["dashboard_id"])

    # Drop page_id columns + the new pages cols
    for table in dependent_tables:
        if _has_column(inspector, table, "page_id"):
            idx_name = f"idx_{table}_page_id"
            fk_name = f"fk_{table}_page_id"
            try:
                op.drop_index(idx_name, table_name=table)
            except Exception:
                pass
            try:
                op.drop_constraint(fk_name, table, type_="foreignkey")
            except Exception:
                pass
            op.drop_column(table, "page_id")

    for col in ("template_id", "is_locked", "canvas_settings"):
        if _has_column(inspector, "pages", col):
            if col == "template_id" and _has_fk(inspector, "pages", "fk_pages_template_id"):
                try:
                    op.drop_constraint("fk_pages_template_id", "pages", type_="foreignkey")
                except Exception:
                    pass
            try:
                op.drop_column("pages", col)
            except Exception:
                pass
