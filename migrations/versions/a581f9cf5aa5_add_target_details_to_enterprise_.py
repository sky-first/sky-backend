"""add target_details to enterprise relationships

Revision ID: a581f9cf5aa5
Revises: ee92f5e0d735
Create Date: 2026-03-10 14:30:24.395297

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a581f9cf5aa5"
down_revision = "ee92f5e0d735"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add target_details column to user_enterprise_relationships
    op.add_column(
        "user_enterprise_relationships",
        sa.Column("target_details", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    pass
    # Remove target_details column from user_enterprise_relationships
    op.drop_column("user_enterprise_relationships", "target_details")
