"""increase_refresh_token_size

Revision ID: 1524ece374b1
Revises: 001_initial
Create Date: 2025-12-04 10:54:37.484212

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1524ece374b1"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alter refresh_tokens.token from VARCHAR(255) to TEXT to support longer JWT tokens
    op.alter_column(
        "refresh_tokens",
        "token",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    pass
    # Revert back to VARCHAR(255) - note: this may fail if tokens longer than 255 exist
    op.alter_column(
        "refresh_tokens",
        "token",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
