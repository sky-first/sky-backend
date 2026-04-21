"""Add z_index column to widgets for layer ordering (shapes + bring-to-front/send-to-back).

Revision ID: add_widget_z_index_20260421
Revises: glossary_terms_20260418
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_widget_z_index_20260421"
down_revision = "glossary_terms_20260418"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column("z_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_widgets_z_index", "widgets", ["dashboard_id", "z_index"])


def downgrade() -> None:
    op.drop_index("idx_widgets_z_index", table_name="widgets")
    op.drop_column("widgets", "z_index")
