"""rename_workspaces_to_planets

Revision ID: 86aad48392e8
Revises: 1524ece374b1
Create Date: 2025-12-04 11:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "86aad48392e8"
down_revision = "1524ece374b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename workspace_members table to planet_members first (to avoid FK conflicts)
    op.rename_table("workspace_members", "planet_members")

    # Rename workspaces table to planets
    op.rename_table("workspaces", "planets")

    # Rename workspace_id column to planet_id in planet_members
    op.alter_column("planet_members", "workspace_id", new_column_name="planet_id")

    # Rename workspace_id column to planet_id in dashboards
    op.alter_column("dashboards", "workspace_id", new_column_name="planet_id")

    # Drop old indexes
    op.drop_index("idx_workspaces_owner_id", table_name="planets")
    op.drop_index("idx_workspaces_type", table_name="planets")
    op.drop_index("idx_workspaces_is_active", table_name="planets")
    op.drop_index("idx_workspaces_last_accessed", table_name="planets")
    op.drop_index("idx_workspace_members_workspace_user", table_name="planet_members")
    op.drop_index("idx_dashboards_workspace_id", table_name="dashboards")

    # Create new indexes
    op.create_index(
        "idx_planets_owner_id",
        "planets",
        ["owner_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_planets_type",
        "planets",
        ["type"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_planets_is_active",
        "planets",
        ["is_active"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_planets_last_accessed", "planets", ["last_accessed"], unique=False
    )
    op.create_index(
        "idx_planet_members_planet_user",
        "planet_members",
        ["planet_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_dashboards_planet_id",
        "dashboards",
        ["planet_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Drop old foreign key constraints and recreate with new names
    op.drop_constraint(
        "workspace_members_workspace_id_fkey", "planet_members", type_="foreignkey"
    )
    op.drop_constraint(
        "workspace_members_user_id_fkey", "planet_members", type_="foreignkey"
    )
    op.drop_constraint("dashboards_workspace_id_fkey", "dashboards", type_="foreignkey")

    # Create new foreign key constraints
    op.create_foreign_key(
        "planet_members_planet_id_fkey",
        "planet_members",
        "planets",
        ["planet_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "planet_members_user_id_fkey",
        "planet_members",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "dashboards_planet_id_fkey",
        "dashboards",
        "planets",
        ["planet_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Rename unique constraint
    op.drop_constraint(
        "uq_workspace_members_workspace_user", "planet_members", type_="unique"
    )
    op.create_unique_constraint(
        "uq_planet_members_planet_user", "planet_members", ["planet_id", "user_id"]
    )


def downgrade() -> None:
    pass
    # Reverse the process
    op.drop_constraint(
        "uq_planet_members_planet_user", "planet_members", type_="unique"
    )
    op.create_unique_constraint(
        "uq_workspace_members_workspace_user",
        "planet_members",
        ["planet_id", "user_id"],
    )

    op.drop_constraint("dashboards_planet_id_fkey", "dashboards", type_="foreignkey")
    op.drop_constraint(
        "planet_members_user_id_fkey", "planet_members", type_="foreignkey"
    )
    op.drop_constraint(
        "planet_members_planet_id_fkey", "planet_members", type_="foreignkey"
    )

    op.create_foreign_key(
        "dashboards_workspace_id_fkey",
        "dashboards",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "workspace_members_user_id_fkey",
        "workspace_members",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "workspace_members_workspace_id_fkey",
        "workspace_members",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("idx_dashboards_planet_id", table_name="dashboards")
    op.drop_index("idx_planet_members_planet_user", table_name="planet_members")
    op.drop_index("idx_planets_last_accessed", table_name="planets")
    op.drop_index("idx_planets_is_active", table_name="planets")
    op.drop_index("idx_planets_type", table_name="planets")
    op.drop_index("idx_planets_owner_id", table_name="planets")

    op.create_index(
        "idx_dashboards_workspace_id",
        "dashboards",
        ["workspace_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_workspace_members_workspace_user",
        "workspace_members",
        ["workspace_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_workspaces_last_accessed", "workspaces", ["last_accessed"], unique=False
    )
    op.create_index(
        "idx_workspaces_is_active",
        "workspaces",
        ["is_active"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_workspaces_type",
        "workspaces",
        ["type"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_workspaces_owner_id",
        "workspaces",
        ["owner_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.alter_column("dashboards", "planet_id", new_column_name="workspace_id")
    op.alter_column("workspace_members", "planet_id", new_column_name="workspace_id")

    op.rename_table("planets", "workspaces")
    op.rename_table("planet_members", "workspace_members")
