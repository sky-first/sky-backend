"""Add Auth0 and SSO fields to users table

Revision ID: add_auth0_fields
Revises: add_role_permissions
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_auth0_fields'
down_revision = 'add_role_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Auth0 integration fields
    op.add_column('users', sa.Column('auth0_id', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('auth_provider', sa.String(50), nullable=False, server_default='local'))
    op.add_column('users', sa.Column('auth_provider_id', sa.String(255), nullable=True))
    
    # Add invite system fields
    op.add_column('users', sa.Column('invite_token', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('invite_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Add SSO metadata field
    op.add_column('users', sa.Column('sso_metadata', postgresql.JSON, nullable=True))
    
    # Create indexes
    op.create_index('idx_users_auth0_id', 'users', ['auth0_id'], unique=True, postgresql_where=sa.text('auth0_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_index('idx_users_auth_provider', 'users', ['auth_provider'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_users_auth_provider_id', 'users', ['auth_provider_id'], unique=False, postgresql_where=sa.text('auth_provider_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_index('idx_users_invite_token', 'users', ['invite_token'], unique=False, postgresql_where=sa.text('invite_token IS NOT NULL'))
    
    # Add foreign key for invited_by
    op.create_foreign_key(
        'fk_users_invited_by',
        'users', 'users',
        ['invited_by'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Drop foreign key
    op.drop_constraint('fk_users_invited_by', 'users', type_='foreignkey')
    
    # Drop indexes
    op.drop_index('idx_users_invite_token', table_name='users')
    op.drop_index('idx_users_auth_provider_id', table_name='users')
    op.drop_index('idx_users_auth_provider', table_name='users')
    op.drop_index('idx_users_auth0_id', table_name='users')
    
    # Drop columns
    op.drop_column('users', 'sso_metadata')
    op.drop_column('users', 'invited_by')
    op.drop_column('users', 'invite_expires_at')
    op.drop_column('users', 'invite_token')
    op.drop_column('users', 'auth_provider_id')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'auth0_id')

