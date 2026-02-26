"""merge_heads

Revision ID: 18611709c429
Revises: c7c41ef7426d, merge_metrics_head_20260225
Create Date: 2026-02-26 17:04:59.071325

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '18611709c429'
down_revision = ('c7c41ef7426d', 'merge_metrics_head_20260225')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

