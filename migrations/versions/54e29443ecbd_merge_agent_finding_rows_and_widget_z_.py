"""merge agent_finding_rows and widget_z_index

Revision ID: 54e29443ecbd
Revises: agent_finding_rows_20260421, add_widget_z_index_20260421
Create Date: 2026-04-21 12:40:13.118491

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '54e29443ecbd'
down_revision = ('agent_finding_rows_20260421', 'add_widget_z_index_20260421')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

