"""add_crew_id_to_semantic_cache

Revision ID: add_sc_crew_id
Revises: merge_metrics_head_20260225
Create Date: 2026-03-10

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_sc_crew_id"
down_revision = "merge_metrics_head_20260225"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add crew_id to semantic_cache for data isolation
    op.add_column("semantic_cache", sa.Column("crew_id", sa.String(), nullable=True))
    op.create_index("ix_semantic_cache_crew_id", "semantic_cache", ["crew_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_semantic_cache_crew_id", table_name="semantic_cache")
    op.drop_column("semantic_cache", "crew_id")
