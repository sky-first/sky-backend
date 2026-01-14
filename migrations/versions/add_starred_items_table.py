"""Add starred_items table

Revision ID: add_starred_items
Revises: add_user_datasets
Create Date: 2025-01-20 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_starred_items'
down_revision = 'add_user_datasets'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'starred_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_type', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_starred_items_user_id', 'starred_items', ['user_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_starred_items_item', 'starred_items', ['item_id', 'item_type'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    # Create unique constraint without WHERE clause (PostgreSQL partial unique indexes need to be created differently)
    op.create_unique_constraint('uq_starred_items_user_item', 'starred_items', ['user_id', 'item_id', 'item_type'])


def downgrade() -> None:
    op.drop_constraint('uq_starred_items_user_item', 'starred_items', type_='unique')
    op.drop_index('idx_starred_items_item', table_name='starred_items')
    op.drop_index('idx_starred_items_user_id', table_name='starred_items')
    op.drop_table('starred_items')

