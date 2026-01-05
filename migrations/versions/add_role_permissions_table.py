"""Add role_permissions table

Revision ID: add_role_permissions
Revises: add_starred_items
Create Date: 2025-01-20 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_role_permissions'
down_revision = 'add_starred_items'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'role_permissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('role', sa.String(50), nullable=False, unique=True),
        sa.Column('permissions', postgresql.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_role_permissions_role', 'role_permissions', ['role'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_role_permissions_role', table_name='role_permissions')
    op.drop_table('role_permissions')

