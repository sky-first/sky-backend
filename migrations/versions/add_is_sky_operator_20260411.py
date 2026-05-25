"""Add is_sky_operator to users table.

Revision ID: add_is_sky_operator_20260411
Revises: add_support_settings_20260410
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "add_is_sky_operator_20260411"
down_revision = "add_support_settings_20260410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_sky_operator",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_sky_operator")
