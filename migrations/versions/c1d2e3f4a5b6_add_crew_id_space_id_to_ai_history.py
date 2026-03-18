"""add_crew_id_space_id_to_ai_history

Revision ID: c1d2e3f4a5b6
Revises: b7d1a2e3f4g5
Create Date: 2026-03-05 09:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "b7d1a2e3f4g5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add space_id and crew_id to ai_history for collaborative context isolation
    op.add_column("ai_history", sa.Column("space_id", sa.String(), nullable=True))
    op.add_column("ai_history", sa.Column("crew_id", sa.String(), nullable=True))

    op.create_index("ix_ai_history_space_id", "ai_history", ["space_id"], unique=False)
    op.create_index("ix_ai_history_crew_id", "ai_history", ["crew_id"], unique=False)


def downgrade() -> None:
    pass
    op.drop_index("ix_ai_history_crew_id", table_name="ai_history")
    op.drop_index("ix_ai_history_space_id", table_name="ai_history")

    op.drop_column("ai_history", "crew_id")
    op.drop_column("ai_history", "space_id")
