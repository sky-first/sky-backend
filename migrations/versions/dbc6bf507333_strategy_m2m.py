"""strategy_m2m

Revision ID: dbc6bf507333
Revises: d66d838fb734
Create Date: 2026-03-26 15:30:06.623365

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json

# revision identifiers, used by Alembic.
revision = 'dbc6bf507333'
down_revision = 'd66d838fb734'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Create association tables
    op.create_table(
        'strategy_initiative_spaces',
        sa.Column('initiative_id', sa.UUID(), sa.ForeignKey('strategy_initiatives.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('space_id', sa.UUID(), sa.ForeignKey('spaces.id', ondelete='CASCADE'), primary_key=True)
    )
    op.create_table(
        'strategy_initiative_crews',
        sa.Column('initiative_id', sa.UUID(), sa.ForeignKey('strategy_initiatives.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('crew_id', sa.UUID(), sa.ForeignKey('crews.id', ondelete='CASCADE'), primary_key=True)
    )

    # 2. Migrate data
    connection = op.get_bind()
    
    # Fetch existing data
    # Note: If running on Postgres, space_ids is JSONB (handled as dict/list). On SQLite, it might be string.
    initiatives = connection.execute(sa.text("SELECT id, space_ids, crew_ids FROM strategy_initiatives")).fetchall()
    
    for row in initiatives:
        init_id = row[0]
        space_ids_json = row[1]
        crew_ids_json = row[2]
        
        if space_ids_json:
            try:
                ids = json.loads(space_ids_json) if isinstance(space_ids_json, str) else space_ids_json
                if isinstance(ids, list):
                    for sid in ids:
                        if sid:
                            connection.execute(sa.text("INSERT INTO strategy_initiative_spaces (initiative_id, space_id) VALUES (:init_id, :sid)"), {"init_id": init_id, "sid": sid})
            except Exception:
                pass
                
        if crew_ids_json:
            try:
                ids = json.loads(crew_ids_json) if isinstance(crew_ids_json, str) else crew_ids_json
                if isinstance(ids, list):
                    for cid in ids:
                        if cid:
                            connection.execute(sa.text("INSERT INTO strategy_initiative_crews (initiative_id, crew_id) VALUES (:init_id, :cid)"), {"init_id": init_id, "cid": cid})
            except Exception:
                pass

    # 3. Remove old columns
    op.drop_column('strategy_initiatives', 'space_ids')
    op.drop_column('strategy_initiatives', 'crew_ids')

def downgrade() -> None:
    # 1. Add back columns
    op.add_column('strategy_initiatives', sa.Column('space_ids', sa.JSON(), nullable=True))
    op.add_column('strategy_initiatives', sa.Column('crew_ids', sa.JSON(), nullable=True))

    # 2. Drop tables
    op.drop_table('strategy_initiative_crews')
    op.drop_table('strategy_initiative_spaces')
