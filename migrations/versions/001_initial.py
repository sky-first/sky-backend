"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-15 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('avatar', sa.Text, nullable=True),
        sa.Column('role', sa.String(50), nullable=False, server_default='user'),
        sa.Column('email_verified', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('onboarding_step', sa.String(50), nullable=False, server_default='0'),
        sa.Column('has_completed_onboarding', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('selected_domain', sa.String(255), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_users_email', 'users', ['email'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_users_role', 'users', ['role'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_users_created_at', 'users', ['created_at'], unique=False)

    # Refresh tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token', sa.String(255), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('idx_refresh_tokens_token', 'refresh_tokens', ['token'], unique=False)
    op.create_index('idx_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'], unique=False)

    # Workspaces table
    op.create_table(
        'workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('color', sa.String(7), nullable=False),
        sa.Column('icon', sa.String(255), nullable=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('last_accessed', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_workspaces_owner_id', 'workspaces', ['owner_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_workspaces_type', 'workspaces', ['type'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_workspaces_is_active', 'workspaces', ['is_active'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_workspaces_last_accessed', 'workspaces', ['last_accessed'], unique=False)

    # Workspace members table
    op.create_table(
        'workspace_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_members_workspace_user'),
    )
    op.create_index('idx_workspace_members_workspace_user', 'workspace_members', ['workspace_id', 'user_id'], unique=True)

    # Dashboards table
    op.create_table(
        'dashboards',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('canvas_settings', postgresql.JSON, nullable=True),
        sa.Column('is_locked', sa.String(50), nullable=False, server_default='false'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_dashboards_workspace_id', 'dashboards', ['workspace_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_dashboards_created_by', 'dashboards', ['created_by'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_dashboards_created_at', 'dashboards', ['created_at'], unique=False)

    # Widgets table
    op.create_table(
        'widgets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('dashboard_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('position', postgresql.JSON, nullable=False),
        sa.Column('size', postgresql.JSON, nullable=False),
        sa.Column('data', postgresql.JSON, nullable=True),
        sa.Column('config', postgresql.JSON, nullable=True),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('query_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['dashboard_id'], ['dashboards.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_widgets_dashboard_id', 'widgets', ['dashboard_id'], unique=False)
    op.create_index('idx_widgets_type', 'widgets', ['type'], unique=False)


def downgrade() -> None:
    op.drop_table('widgets')
    op.drop_table('dashboards')
    op.drop_table('workspace_members')
    op.drop_table('workspaces')
    op.drop_table('refresh_tokens')
    op.drop_table('users')

