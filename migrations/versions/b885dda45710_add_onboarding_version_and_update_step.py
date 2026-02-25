"""add_onboarding_version_and_update_step

Revision ID: b885dda45710
Revises: f17ab2df9283
Create Date: 2026-02-20 12:13:31.582995

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b885dda45710'
down_revision = 'f17ab2df9283'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ai_history ---
    op.create_index(op.f('ix_ai_history_planet_id'), 'ai_history', ['planet_id'], unique=False)
    # --- ai_queries ---
    op.create_index(op.f('ix_ai_queries_planet_id'), 'ai_queries', ['planet_id'], unique=False)
    # --- chat_messages ---
    op.create_index(op.f('ix_chat_messages_planet_id'), 'chat_messages', ['planet_id'], unique=False)
    
    # --- users ---
    op.add_column('users', sa.Column('onboarding_version', sa.Integer(), server_default='0', nullable=False))
    
    # Handle onboarding_step conversion carefully
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step TYPE INTEGER USING onboarding_step::integer")
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step SET DEFAULT 0")
    op.alter_column('users', 'onboarding_step',
               existing_type=sa.Integer(),
               nullable=True)


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step TYPE VARCHAR(50) USING onboarding_step::text")
    op.execute("ALTER TABLE users ALTER COLUMN onboarding_step SET DEFAULT '0'")
    op.alter_column('users', 'onboarding_step',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.drop_column('users', 'onboarding_version')
    op.drop_index(op.f('ix_chat_messages_planet_id'), table_name='chat_messages')
    op.drop_index(op.f('ix_ai_queries_planet_id'), table_name='ai_queries')
    op.drop_index(op.f('ix_ai_history_planet_id'), table_name='ai_history')
