"""merge_all_heads_20260428

Revision ID: merge_all_heads_20260428
Revises: demo_space_user_ttl_20260427, e6e9eef87b74
Create Date: 2026-04-28 11:45:19.324559

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_all_heads_20260428'
down_revision = ('demo_space_user_ttl_20260427', 'e6e9eef87b74')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

