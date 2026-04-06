"""rename planets to pages

Revision ID: a3f2c1d0e9b8
Revises: fd74af4b3c14
Create Date: 2026-03-28 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f2c1d0e9b8"
down_revision = "fd74af4b3c14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Drop FK constraints that reference planets / planet_members
    # ------------------------------------------------------------------ #
    # dashboards.planet_id -> planets.id
    op.drop_constraint("dashboards_planet_id_fkey", "dashboards", type_="foreignkey")
    # ai_queries.planet_id -> planets.id
    op.drop_constraint("fk_ai_queries_planet_id_planets", "ai_queries", type_="foreignkey")
    # ai_history.planet_id -> planets.id
    op.drop_constraint("fk_ai_history_planet_id_planets", "ai_history", type_="foreignkey")
    # chat_messages.planet_id -> planets.id
    op.drop_constraint("fk_chat_messages_planet_id_planets", "chat_messages", type_="foreignkey")
    # dashboard_build_jobs.planet_id -> planets.id
    op.drop_constraint("dashboard_build_jobs_planet_id_fkey", "dashboard_build_jobs", type_="foreignkey")
    # intelligence_signals.planet_id -> planets.id
    op.drop_constraint("intelligence_signals_planet_id_fkey", "intelligence_signals", type_="foreignkey")
    # planet_members.planet_id -> planets.id
    op.drop_constraint("planet_members_planet_id_fkey", "planet_members", type_="foreignkey")
    # planet_members.user_id -> users.id  (kept but need to recreate after table rename)
    op.drop_constraint("planet_members_user_id_fkey", "planet_members", type_="foreignkey")

    # ------------------------------------------------------------------ #
    # 2. Drop indexes on old column/table names
    # ------------------------------------------------------------------ #
    op.drop_index("idx_planets_owner_id", table_name="planets")
    op.drop_index("idx_planets_type", table_name="planets")
    op.drop_index("idx_planets_is_active", table_name="planets")
    op.drop_index("idx_planets_last_accessed", table_name="planets")
    op.drop_constraint("uq_planet_members_planet_user", "planet_members", type_="unique")
    op.drop_index("idx_planet_members_planet_user", table_name="planet_members")

    op.drop_index("idx_dashboards_planet_id", table_name="dashboards")
    op.drop_index("idx_ai_queries_planet_id", table_name="ai_queries")
    op.drop_index("idx_ai_queries_planet_created", table_name="ai_queries")
    op.drop_index("idx_ai_history_planet_id", table_name="ai_history")
    op.drop_index("idx_ai_history_planet_created", table_name="ai_history")
    op.drop_index("idx_chat_messages_planet_id", table_name="chat_messages")
    op.drop_index("idx_chat_messages_planet_created", table_name="chat_messages")

    # ------------------------------------------------------------------ #
    # 3. Rename tables
    # ------------------------------------------------------------------ #
    op.rename_table("planets", "pages")
    op.rename_table("planet_members", "page_members")

    # ------------------------------------------------------------------ #
    # 4. Rename planet_id columns to page_id in FK tables
    # ------------------------------------------------------------------ #
    op.alter_column("dashboards", "planet_id", new_column_name="page_id")
    op.alter_column("ai_queries", "planet_id", new_column_name="page_id")
    op.alter_column("ai_history", "planet_id", new_column_name="page_id")
    op.alter_column("chat_messages", "planet_id", new_column_name="page_id")
    op.alter_column("dashboard_build_jobs", "planet_id", new_column_name="page_id")
    op.alter_column("intelligence_signals", "planet_id", new_column_name="page_id")
    op.alter_column("page_members", "planet_id", new_column_name="page_id")

    # ------------------------------------------------------------------ #
    # 5. Recreate indexes with new names
    # ------------------------------------------------------------------ #
    op.create_index("idx_pages_owner_id", "pages", ["owner_id"])
    op.create_index("idx_pages_type", "pages", ["type"])
    op.create_index("idx_pages_is_active", "pages", ["is_active"])
    op.create_index("idx_pages_last_accessed", "pages", ["last_accessed"])
    op.create_index("idx_page_members_page_user", "page_members", ["page_id", "user_id"], unique=True)

    op.create_index("idx_dashboards_page_id", "dashboards", ["page_id"])
    op.create_index("idx_ai_queries_page_id", "ai_queries", ["page_id"])
    op.create_index("idx_ai_queries_page_created", "ai_queries", ["page_id", "created_at"])
    op.create_index("idx_ai_history_page_id", "ai_history", ["page_id"])
    op.create_index("idx_ai_history_page_created", "ai_history", ["page_id", "created_at"])
    op.create_index("idx_chat_messages_page_id", "chat_messages", ["page_id"])
    op.create_index("idx_chat_messages_page_created", "chat_messages", ["page_id", "created_at"])

    # ------------------------------------------------------------------ #
    # 6. Recreate FK constraints pointing to new table/column names
    # ------------------------------------------------------------------ #
    op.create_foreign_key(
        "dashboards_page_id_fkey", "dashboards", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "ai_queries_page_id_fkey", "ai_queries", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "ai_history_page_id_fkey", "ai_history", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "chat_messages_page_id_fkey", "chat_messages", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "dashboard_build_jobs_page_id_fkey", "dashboard_build_jobs", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "intelligence_signals_page_id_fkey", "intelligence_signals", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "page_members_page_id_fkey", "page_members", "pages", ["page_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "page_members_user_id_fkey", "page_members", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    # ------------------------------------------------------------------ #
    # Reverse: pages -> planets, page_members -> planet_members, page_id -> planet_id
    # ------------------------------------------------------------------ #
    # Drop new FK constraints
    op.drop_constraint("dashboards_page_id_fkey", "dashboards", type_="foreignkey")
    op.drop_constraint("ai_queries_page_id_fkey", "ai_queries", type_="foreignkey")
    op.drop_constraint("ai_history_page_id_fkey", "ai_history", type_="foreignkey")
    op.drop_constraint("chat_messages_page_id_fkey", "chat_messages", type_="foreignkey")
    op.drop_constraint("dashboard_build_jobs_page_id_fkey", "dashboard_build_jobs", type_="foreignkey")
    op.drop_constraint("intelligence_signals_page_id_fkey", "intelligence_signals", type_="foreignkey")
    op.drop_constraint("page_members_page_id_fkey", "page_members", type_="foreignkey")
    op.drop_constraint("page_members_user_id_fkey", "page_members", type_="foreignkey")

    # Drop new indexes
    op.drop_index("idx_pages_owner_id", table_name="pages")
    op.drop_index("idx_pages_type", table_name="pages")
    op.drop_index("idx_pages_is_active", table_name="pages")
    op.drop_index("idx_pages_last_accessed", table_name="pages")
    op.drop_index("idx_page_members_page_user", table_name="page_members")
    op.drop_index("idx_dashboards_page_id", table_name="dashboards")
    op.drop_index("idx_ai_queries_page_id", table_name="ai_queries")
    op.drop_index("idx_ai_queries_page_created", table_name="ai_queries")
    op.drop_index("idx_ai_history_page_id", table_name="ai_history")
    op.drop_index("idx_ai_history_page_created", table_name="ai_history")
    op.drop_index("idx_chat_messages_page_id", table_name="chat_messages")
    op.drop_index("idx_chat_messages_page_created", table_name="chat_messages")

    # Rename columns back
    op.alter_column("dashboards", "page_id", new_column_name="planet_id")
    op.alter_column("ai_queries", "page_id", new_column_name="planet_id")
    op.alter_column("ai_history", "page_id", new_column_name="planet_id")
    op.alter_column("chat_messages", "page_id", new_column_name="planet_id")
    op.alter_column("dashboard_build_jobs", "page_id", new_column_name="planet_id")
    op.alter_column("intelligence_signals", "page_id", new_column_name="planet_id")
    op.alter_column("page_members", "page_id", new_column_name="planet_id")

    # Rename tables back
    op.rename_table("pages", "planets")
    op.rename_table("page_members", "planet_members")

    # Recreate old indexes
    op.create_index("idx_planets_owner_id", "planets", ["owner_id"])
    op.create_index("idx_planets_type", "planets", ["type"])
    op.create_index("idx_planets_is_active", "planets", ["is_active"])
    op.create_index("idx_planets_last_accessed", "planets", ["last_accessed"])
    op.create_unique_constraint("uq_planet_members_planet_user", "planet_members", ["planet_id", "user_id"])
    op.create_index("idx_planet_members_planet_user", "planet_members", ["planet_id", "user_id"])
    op.create_index("idx_dashboards_planet_id", "dashboards", ["planet_id"])
    op.create_index("idx_ai_queries_planet_id", "ai_queries", ["planet_id"])
    op.create_index("idx_ai_queries_planet_created", "ai_queries", ["planet_id", "created_at"])
    op.create_index("idx_ai_history_planet_id", "ai_history", ["planet_id"])
    op.create_index("idx_ai_history_planet_created", "ai_history", ["planet_id", "created_at"])
    op.create_index("idx_chat_messages_planet_id", "chat_messages", ["planet_id"])
    op.create_index("idx_chat_messages_planet_created", "chat_messages", ["planet_id", "created_at"])

    # Recreate old FK constraints
    op.create_foreign_key(
        "dashboards_planet_id_fkey", "dashboards", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_ai_queries_planet_id_planets", "ai_queries", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_ai_history_planet_id_planets", "ai_history", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_chat_messages_planet_id_planets", "chat_messages", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "dashboard_build_jobs_planet_id_fkey", "dashboard_build_jobs", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "intelligence_signals_planet_id_fkey", "intelligence_signals", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "planet_members_planet_id_fkey", "planet_members", "planets", ["planet_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "planet_members_user_id_fkey", "planet_members", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
