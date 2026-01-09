"""Add Auth0 and SSO fields to users table

Revision ID: add_auth0_fields
Revises: add_role_permissions
Create Date: 2025-01-20 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_auth0_fields'
down_revision = 'add_role_permissions'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar()
    )


def _index_exists(index_name: str, table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = :table_name
                      AND indexname = :index_name
                )
                """
            ),
            {"table_name": table_name, "index_name": index_name},
        ).scalar()
    )


def _constraint_exists(constraint_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = :constraint_name
                )
                """
            ),
            {"constraint_name": constraint_name},
        ).scalar()
    )


def upgrade() -> None:
    # Add Auth0 integration fields
    if not _column_exists("users", "auth0_id"):
        op.add_column('users', sa.Column('auth0_id', sa.String(255), nullable=True))
    if not _column_exists("users", "auth_provider"):
        op.add_column('users', sa.Column('auth_provider', sa.String(50), nullable=False, server_default='local'))
    if not _column_exists("users", "auth_provider_id"):
        op.add_column('users', sa.Column('auth_provider_id', sa.String(255), nullable=True))
    
    # Add invite system fields
    if not _column_exists("users", "invite_token"):
        op.add_column('users', sa.Column('invite_token', sa.String(255), nullable=True))
    if not _column_exists("users", "invite_expires_at"):
        op.add_column('users', sa.Column('invite_expires_at', sa.DateTime(timezone=True), nullable=True))
    if not _column_exists("users", "invited_by"):
        op.add_column('users', sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Add SSO metadata field
    if not _column_exists("users", "sso_metadata"):
        op.add_column('users', sa.Column('sso_metadata', postgresql.JSON, nullable=True))
    
    # Create indexes
    if not _index_exists("idx_users_auth0_id", "users"):
        op.create_index('idx_users_auth0_id', 'users', ['auth0_id'], unique=True, postgresql_where=sa.text('auth0_id IS NOT NULL AND deleted_at IS NULL'))
    if not _index_exists("idx_users_auth_provider", "users"):
        op.create_index('idx_users_auth_provider', 'users', ['auth_provider'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    if not _index_exists("idx_users_auth_provider_id", "users"):
        op.create_index('idx_users_auth_provider_id', 'users', ['auth_provider_id'], unique=False, postgresql_where=sa.text('auth_provider_id IS NOT NULL AND deleted_at IS NULL'))
    if not _index_exists("idx_users_invite_token", "users"):
        op.create_index('idx_users_invite_token', 'users', ['invite_token'], unique=False, postgresql_where=sa.text('invite_token IS NOT NULL'))
    
    # Add foreign key for invited_by
    if not _constraint_exists("fk_users_invited_by"):
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

