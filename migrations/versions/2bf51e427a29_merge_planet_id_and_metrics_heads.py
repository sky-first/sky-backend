"""merge_planet_id_and_metrics_heads

Revision ID: 2bf51e427a29
Revises: b885dda45710, merge_metrics_head_20260225
Create Date: 2026-02-26 08:40:24.017517

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bf51e427a29'
down_revision = ('b885dda45710', 'merge_metrics_head_20260225')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

