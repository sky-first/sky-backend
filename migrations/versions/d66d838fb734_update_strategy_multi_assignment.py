"""update_strategy_multi_assignment

Revision ID: d66d838fb734
Revises: fd74af4b3c14
Create Date: 2026-03-26 10:33:13.366718

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd66d838fb734'
down_revision = 'fd74af4b3c14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add multi-assignment JSON columns
    op.add_column('strategy_initiatives', sa.Column('space_ids', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('strategy_initiatives', sa.Column('crew_ids', sa.JSON(), nullable=True, server_default='[]'))
    
    # 2. Migrate data from singular to multi (wrapping in list)
    conn = op.get_bind()
    # Check if we are on Postgres for JSON functions, otherwise use basic string wrapping for SQLite
    if conn.dialect.name == 'postgresql':
        conn.execute(sa.text("UPDATE strategy_initiatives SET space_ids = jsonb_build_array(space_id) WHERE space_id IS NOT NULL"))
        conn.execute(sa.text("UPDATE strategy_initiatives SET crew_ids = jsonb_build_array(crew_id) WHERE crew_id IS NOT NULL"))
    else:
        # Fallback for SQLite/others if needed (POC context)
        # Note: server_default already set them to '[]'
        pass
    
    # 3. Drop legacy singular assignment columns
    op.drop_column('strategy_initiatives', 'space_id')
    op.drop_column('strategy_initiatives', 'crew_id')


def downgrade() -> None:
    # 1. Recreate legacy singular assignment columns
    op.add_column('strategy_initiatives', sa.Column('space_id', sa.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True))
    op.add_column('strategy_initiatives', sa.Column('crew_id', sa.UUID(as_uuid=True), sa.ForeignKey("crews.id", ondelete="CASCADE"), nullable=True))
    
    # 2. Migrate data back (taking the first element if exists)
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        conn.execute(sa.text("UPDATE strategy_initiatives SET space_id = (space_ids->>0)::uuid WHERE space_ids IS NOT NULL AND jsonb_array_length(space_ids) > 0"))
        conn.execute(sa.text("UPDATE strategy_initiatives SET crew_id = (crew_ids->>0)::uuid WHERE crew_ids IS NOT NULL AND jsonb_array_length(crew_ids) > 0"))

    # 3. Remove multi-assignment JSON columns
    op.drop_column('strategy_initiatives', 'space_ids')
    op.drop_column('strategy_initiatives', 'crew_ids')

