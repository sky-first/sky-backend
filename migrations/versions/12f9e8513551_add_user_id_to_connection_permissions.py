"""add user_id to connection_permissions

Revision ID: 12f9e8513551
Revises: a581f9cf5aa5
Create Date: 2026-03-10 14:38:16.247054

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "12f9e8513551"
down_revision = "a581f9cf5aa5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add user_id column
    op.add_column(
        "connection_permissions", sa.Column("user_id", sa.UUID(), nullable=True)
    )

    # 2. Add foreign key for user_id
    op.create_foreign_key(
        "connection_permissions_user_id_fkey",
        "connection_permissions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Update unique constraint
    # First drop the old one
    op.drop_constraint(
        "uq_connection_permissions", "connection_permissions", type_="unique"
    )
    # Create new one with user_id
    op.create_unique_constraint(
        "uq_connection_permissions",
        "connection_permissions",
        ["connection_id", "space_id", "crew_id", "user_id"],
    )

    # 4. Add index for user_id
    op.create_index(
        "idx_connection_permissions_user_id",
        "connection_permissions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    pass
    # 1. Drop index
    op.drop_index(
        "idx_connection_permissions_user_id", table_name="connection_permissions"
    )

    # 2. Revert unique constraint
    op.drop_constraint(
        "uq_connection_permissions", "connection_permissions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_connection_permissions",
        "connection_permissions",
        ["connection_id", "space_id", "crew_id"],
    )

    # 3. Drop foreign key
    op.drop_constraint(
        "connection_permissions_user_id_fkey",
        "connection_permissions",
        type_="foreignkey",
    )

    # 4. Drop column
    op.drop_column("connection_permissions", "user_id")
