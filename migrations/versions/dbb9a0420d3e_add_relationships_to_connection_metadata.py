"""add relationships to connection metadata

Revision ID: dbb9a0420d3e
Revises: 380964cb0112
Create Date: 2026-03-13 12:13:42.884057

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "dbb9a0420d3e"
down_revision = "380964cb0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add relationships column to connection_metadata table
    op.add_column(
        "connection_metadata", sa.Column("relationships", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    # Remove relationships column from connection_metadata table
    op.drop_column("connection_metadata", "relationships")
