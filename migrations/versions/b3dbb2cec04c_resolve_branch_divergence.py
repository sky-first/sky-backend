"""resolve branch divergence

Revision ID: b3dbb2cec04c
Revises: c7c41ef7426d, merge_metrics_head_20260225
Create Date: 2026-02-27 14:47:48.622585

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3dbb2cec04c'
down_revision = ('c7c41ef7426d', 'merge_metrics_head_20260225')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

