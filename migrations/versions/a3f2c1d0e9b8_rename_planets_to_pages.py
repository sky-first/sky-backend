"""rename planets to pages

Revision ID: a3f2c1d0e9b8
Revises: fd74af4b3c14
Create Date: 2026-03-28 10:00:00.000000

Fully idempotent: each drop/rename/create checks for existence first,
so this migration can run cleanly from any partially-migrated state
(e.g. databases where constraints were created with different names
or never created at all).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f2c1d0e9b8"
down_revision = "fd74af4b3c14"
branch_labels = None
depends_on = None


# ─── idempotency helpers ─────────────────────────────────────────────── #

def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT to_regclass(:name)"), {"name": f"public.{name}"}
    ).scalar()
    return result is not None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return result is not None


def _index_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
        {"n": name},
    ).scalar()
    return result is not None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :t AND constraint_name = :c"
        ),
        {"t": table, "c": constraint},
    ).scalar()
    return result is not None


def upgrade() -> None:
    conn = op.get_bind()

    # Idempotency: if rename already happened, nothing to do
    if _table_exists(conn, "pages") and not _table_exists(conn, "planets"):
        return

    # ------------------------------------------------------------------ #
    # 1. Drop FK constraints that reference planets / planet_members
    # ------------------------------------------------------------------ #
    fk_drops = [
        ("dashboards", "dashboards_planet_id_fkey"),
        ("ai_queries", "fk_ai_queries_planet_id_planets"),
        ("ai_history", "fk_ai_history_planet_id_planets"),
        ("chat_messages", "fk_chat_messages_planet_id_planets"),
        ("dashboard_build_jobs", "dashboard_build_jobs_planet_id_fkey"),
        ("intelligence_signals", "intelligence_signals_planet_id_fkey"),
        ("planet_members", "planet_members_planet_id_fkey"),
        ("planet_members", "planet_members_user_id_fkey"),
    ]
    for table, constraint in fk_drops:
        if _table_exists(conn, table) and _constraint_exists(conn, table, constraint):
            op.drop_constraint(constraint, table, type_="foreignkey")

    # ------------------------------------------------------------------ #
    # 2. Drop indexes and unique constraint on old names
    # ------------------------------------------------------------------ #
    index_drops = [
        ("idx_planets_owner_id", "planets"),
        ("idx_planets_type", "planets"),
        ("idx_planets_is_active", "planets"),
        ("idx_planets_last_accessed", "planets"),
        ("idx_planet_members_planet_user", "planet_members"),
        ("idx_dashboards_planet_id", "dashboards"),
        ("idx_ai_queries_planet_id", "ai_queries"),
        ("idx_ai_queries_planet_created", "ai_queries"),
        ("idx_ai_history_planet_id", "ai_history"),
        ("idx_ai_history_planet_created", "ai_history"),
        ("idx_chat_messages_planet_id", "chat_messages"),
        ("idx_chat_messages_planet_created", "chat_messages"),
    ]
    for index, table in index_drops:
        if _index_exists(conn, index):
            op.drop_index(index, table_name=table)

    # Unique constraint (may or may not exist depending on environment)
    if _table_exists(conn, "planet_members") and _constraint_exists(
        conn, "planet_members", "uq_planet_members_planet_user"
    ):
        op.drop_constraint("uq_planet_members_planet_user", "planet_members", type_="unique")

    # ------------------------------------------------------------------ #
    # 3. Rename tables
    # ------------------------------------------------------------------ #
    if _table_exists(conn, "planets") and not _table_exists(conn, "pages"):
        op.rename_table("planets", "pages")

    if _table_exists(conn, "planet_members") and not _table_exists(conn, "page_members"):
        op.rename_table("planet_members", "page_members")

    # ------------------------------------------------------------------ #
    # 4. Rename planet_id columns to page_id
    # ------------------------------------------------------------------ #
    column_renames = [
        "dashboards",
        "ai_queries",
        "ai_history",
        "chat_messages",
        "dashboard_build_jobs",
        "intelligence_signals",
        "page_members",
    ]
    for table in column_renames:
        if (
            _table_exists(conn, table)
            and _column_exists(conn, table, "planet_id")
            and not _column_exists(conn, table, "page_id")
        ):
            op.alter_column(table, "planet_id", new_column_name="page_id")

    # ------------------------------------------------------------------ #
    # 5. Recreate indexes with new names
    # ------------------------------------------------------------------ #
    index_definitions = [
        ("idx_pages_owner_id", "pages", ["owner_id"], False),
        ("idx_pages_type", "pages", ["type"], False),
        ("idx_pages_is_active", "pages", ["is_active"], False),
        ("idx_pages_last_accessed", "pages", ["last_accessed"], False),
        ("idx_page_members_page_user", "page_members", ["page_id", "user_id"], True),
        ("idx_dashboards_page_id", "dashboards", ["page_id"], False),
        ("idx_ai_queries_page_id", "ai_queries", ["page_id"], False),
        ("idx_ai_queries_page_created", "ai_queries", ["page_id", "created_at"], False),
        ("idx_ai_history_page_id", "ai_history", ["page_id"], False),
        ("idx_ai_history_page_created", "ai_history", ["page_id", "created_at"], False),
        ("idx_chat_messages_page_id", "chat_messages", ["page_id"], False),
        ("idx_chat_messages_page_created", "chat_messages", ["page_id", "created_at"], False),
    ]
    for name, table, columns, unique in index_definitions:
        if _table_exists(conn, table) and not _index_exists(conn, name):
            op.create_index(name, table, columns, unique=unique)

    # ------------------------------------------------------------------ #
    # 6. Recreate FK constraints pointing to new table/column names
    # ------------------------------------------------------------------ #
    fk_definitions = [
        ("dashboards_page_id_fkey", "dashboards", "pages", ["page_id"], ["id"]),
        ("ai_queries_page_id_fkey", "ai_queries", "pages", ["page_id"], ["id"]),
        ("ai_history_page_id_fkey", "ai_history", "pages", ["page_id"], ["id"]),
        ("chat_messages_page_id_fkey", "chat_messages", "pages", ["page_id"], ["id"]),
        ("dashboard_build_jobs_page_id_fkey", "dashboard_build_jobs", "pages", ["page_id"], ["id"]),
        ("intelligence_signals_page_id_fkey", "intelligence_signals", "pages", ["page_id"], ["id"]),
        ("page_members_page_id_fkey", "page_members", "pages", ["page_id"], ["id"]),
    ]
    for name, source, target, local_cols, remote_cols in fk_definitions:
        if (
            _table_exists(conn, source)
            and _table_exists(conn, target)
            and _column_exists(conn, source, local_cols[0])
            and not _constraint_exists(conn, source, name)
        ):
            op.create_foreign_key(
                name, source, target, local_cols, remote_cols, ondelete="CASCADE"
            )

    # page_members.user_id -> users.id
    if (
        _table_exists(conn, "page_members")
        and _table_exists(conn, "users")
        and not _constraint_exists(conn, "page_members", "page_members_user_id_fkey")
    ):
        op.create_foreign_key(
            "page_members_user_id_fkey",
            "page_members",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Idempotency: if already reverted, nothing to do
    if _table_exists(conn, "planets") and not _table_exists(conn, "pages"):
        return

    # Drop new FK constraints
    new_fks = [
        ("dashboards", "dashboards_page_id_fkey"),
        ("ai_queries", "ai_queries_page_id_fkey"),
        ("ai_history", "ai_history_page_id_fkey"),
        ("chat_messages", "chat_messages_page_id_fkey"),
        ("dashboard_build_jobs", "dashboard_build_jobs_page_id_fkey"),
        ("intelligence_signals", "intelligence_signals_page_id_fkey"),
        ("page_members", "page_members_page_id_fkey"),
        ("page_members", "page_members_user_id_fkey"),
    ]
    for table, constraint in new_fks:
        if _table_exists(conn, table) and _constraint_exists(conn, table, constraint):
            op.drop_constraint(constraint, table, type_="foreignkey")

    # Drop new indexes
    new_indexes = [
        ("idx_pages_owner_id", "pages"),
        ("idx_pages_type", "pages"),
        ("idx_pages_is_active", "pages"),
        ("idx_pages_last_accessed", "pages"),
        ("idx_page_members_page_user", "page_members"),
        ("idx_dashboards_page_id", "dashboards"),
        ("idx_ai_queries_page_id", "ai_queries"),
        ("idx_ai_queries_page_created", "ai_queries"),
        ("idx_ai_history_page_id", "ai_history"),
        ("idx_ai_history_page_created", "ai_history"),
        ("idx_chat_messages_page_id", "chat_messages"),
        ("idx_chat_messages_page_created", "chat_messages"),
    ]
    for index, table in new_indexes:
        if _index_exists(conn, index):
            op.drop_index(index, table_name=table)

    # Rename columns back
    for table in [
        "dashboards",
        "ai_queries",
        "ai_history",
        "chat_messages",
        "dashboard_build_jobs",
        "intelligence_signals",
        "page_members",
    ]:
        if (
            _table_exists(conn, table)
            and _column_exists(conn, table, "page_id")
            and not _column_exists(conn, table, "planet_id")
        ):
            op.alter_column(table, "page_id", new_column_name="planet_id")

    # Rename tables back
    if _table_exists(conn, "pages") and not _table_exists(conn, "planets"):
        op.rename_table("pages", "planets")
    if _table_exists(conn, "page_members") and not _table_exists(conn, "planet_members"):
        op.rename_table("page_members", "planet_members")

    # Recreate old indexes
    old_indexes = [
        ("idx_planets_owner_id", "planets", ["owner_id"], False),
        ("idx_planets_type", "planets", ["type"], False),
        ("idx_planets_is_active", "planets", ["is_active"], False),
        ("idx_planets_last_accessed", "planets", ["last_accessed"], False),
        ("idx_planet_members_planet_user", "planet_members", ["planet_id", "user_id"], False),
        ("idx_dashboards_planet_id", "dashboards", ["planet_id"], False),
        ("idx_ai_queries_planet_id", "ai_queries", ["planet_id"], False),
        ("idx_ai_queries_planet_created", "ai_queries", ["planet_id", "created_at"], False),
        ("idx_ai_history_planet_id", "ai_history", ["planet_id"], False),
        ("idx_ai_history_planet_created", "ai_history", ["planet_id", "created_at"], False),
        ("idx_chat_messages_planet_id", "chat_messages", ["planet_id"], False),
        ("idx_chat_messages_planet_created", "chat_messages", ["planet_id", "created_at"], False),
    ]
    for name, table, columns, unique in old_indexes:
        if _table_exists(conn, table) and not _index_exists(conn, name):
            op.create_index(name, table, columns, unique=unique)

    # Recreate unique constraint
    if _table_exists(conn, "planet_members") and not _constraint_exists(
        conn, "planet_members", "uq_planet_members_planet_user"
    ):
        op.create_unique_constraint(
            "uq_planet_members_planet_user",
            "planet_members",
            ["planet_id", "user_id"],
        )

    # Recreate old FK constraints
    old_fks = [
        ("dashboards_planet_id_fkey", "dashboards", "planets"),
        ("fk_ai_queries_planet_id_planets", "ai_queries", "planets"),
        ("fk_ai_history_planet_id_planets", "ai_history", "planets"),
        ("fk_chat_messages_planet_id_planets", "chat_messages", "planets"),
        ("dashboard_build_jobs_planet_id_fkey", "dashboard_build_jobs", "planets"),
        ("intelligence_signals_planet_id_fkey", "intelligence_signals", "planets"),
        ("planet_members_planet_id_fkey", "planet_members", "planets"),
    ]
    for name, source, target in old_fks:
        if (
            _table_exists(conn, source)
            and _table_exists(conn, target)
            and not _constraint_exists(conn, source, name)
        ):
            op.create_foreign_key(
                name, source, target, ["planet_id"], ["id"], ondelete="CASCADE"
            )

    if (
        _table_exists(conn, "planet_members")
        and _table_exists(conn, "users")
        and not _constraint_exists(conn, "planet_members", "planet_members_user_id_fkey")
    ):
        op.create_foreign_key(
            "planet_members_user_id_fkey",
            "planet_members",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
