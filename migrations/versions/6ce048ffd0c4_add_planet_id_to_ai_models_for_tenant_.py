"""Add planet_id to AI models for tenant isolation

Revision ID: 6ce048ffd0c4
Revises: b912b9ad4a0b
Create Date: 2026-02-20 10:10:29.181753

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '6ce048ffd0c4'
down_revision = 'b912b9ad4a0b'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column}
    ).fetchone()
    return result is not None


def _index_exists(index_name):
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :i"
        ),
        {"i": index_name}
    ).fetchone()
    return result is not None


def _fk_exists(constraint_name, table):
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :c AND table_name = :t"
        ),
        {"c": constraint_name, "t": table}
    ).fetchone()
    return result is not None


def upgrade() -> None:
    # --- ai_history ---
    if not _column_exists('ai_history', 'planet_id'):
        op.add_column('ai_history', sa.Column('planet_id', sa.UUID(), nullable=True))
    if not _index_exists('idx_ai_history_planet_id'):
        op.create_index('idx_ai_history_planet_id', 'ai_history', ['planet_id'], unique=False)
    if not _index_exists('idx_ai_history_planet_created'):
        op.create_index('idx_ai_history_planet_created', 'ai_history', ['planet_id', 'created_at'], unique=False)
    if not _fk_exists('fk_ai_history_planet_id_planets', 'ai_history'):
        op.create_foreign_key('fk_ai_history_planet_id_planets', 'ai_history', 'planets', ['planet_id'], ['id'], ondelete='CASCADE')

    # --- ai_queries ---
    if not _column_exists('ai_queries', 'planet_id'):
        op.add_column('ai_queries', sa.Column('planet_id', sa.UUID(), nullable=True))
    if not _index_exists('idx_ai_queries_planet_id'):
        op.create_index('idx_ai_queries_planet_id', 'ai_queries', ['planet_id'], unique=False)
    if not _index_exists('idx_ai_queries_planet_created'):
        op.create_index('idx_ai_queries_planet_created', 'ai_queries', ['planet_id', 'created_at'], unique=False)
    if not _fk_exists('fk_ai_queries_planet_id_planets', 'ai_queries'):
        op.create_foreign_key('fk_ai_queries_planet_id_planets', 'ai_queries', 'planets', ['planet_id'], ['id'], ondelete='CASCADE')

    # --- chat_messages ---
    if not _column_exists('chat_messages', 'planet_id'):
        op.add_column('chat_messages', sa.Column('planet_id', sa.UUID(), nullable=True))
    if not _index_exists('idx_chat_messages_planet_id'):
        op.create_index('idx_chat_messages_planet_id', 'chat_messages', ['planet_id'], unique=False)
    if not _index_exists('idx_chat_messages_planet_created'):
        op.create_index('idx_chat_messages_planet_created', 'chat_messages', ['planet_id', 'created_at'], unique=False)
    if not _fk_exists('fk_chat_messages_planet_id_planets', 'chat_messages'):
        op.create_foreign_key('fk_chat_messages_planet_id_planets', 'chat_messages', 'planets', ['planet_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    # --- chat_messages ---
    if _fk_exists('fk_chat_messages_planet_id_planets', 'chat_messages'):
        op.drop_constraint('fk_chat_messages_planet_id_planets', 'chat_messages', type_='foreignkey')
    if _index_exists('idx_chat_messages_planet_created'):
        op.drop_index('idx_chat_messages_planet_created', table_name='chat_messages')
    if _index_exists('idx_chat_messages_planet_id'):
        op.drop_index('idx_chat_messages_planet_id', table_name='chat_messages')
    if _column_exists('chat_messages', 'planet_id'):
        op.drop_column('chat_messages', 'planet_id')

    # --- ai_queries ---
    if _fk_exists('fk_ai_queries_planet_id_planets', 'ai_queries'):
        op.drop_constraint('fk_ai_queries_planet_id_planets', 'ai_queries', type_='foreignkey')
    if _index_exists('idx_ai_queries_planet_created'):
        op.drop_index('idx_ai_queries_planet_created', table_name='ai_queries')
    if _index_exists('idx_ai_queries_planet_id'):
        op.drop_index('idx_ai_queries_planet_id', table_name='ai_queries')
    if _column_exists('ai_queries', 'planet_id'):
        op.drop_column('ai_queries', 'planet_id')

    # --- ai_history ---
    if _fk_exists('fk_ai_history_planet_id_planets', 'ai_history'):
        op.drop_constraint('fk_ai_history_planet_id_planets', 'ai_history', type_='foreignkey')
    if _index_exists('idx_ai_history_planet_created'):
        op.drop_index('idx_ai_history_planet_created', table_name='ai_history')
    if _index_exists('idx_ai_history_planet_id'):
        op.drop_index('idx_ai_history_planet_id', table_name='ai_history')
    if _column_exists('ai_history', 'planet_id'):
        op.drop_column('ai_history', 'planet_id')

