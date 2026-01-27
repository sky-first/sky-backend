"""add widget_connections table

Revision ID: 3f17472d08d9
Revises: fix_missing_tables_20260123
Create Date: 2026-01-26 09:28:57.196060

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '3f17472d08d9'
down_revision = 'fix_missing_tables_20260123'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create widget_connections table if it doesn't exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS widget_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dashboard_id UUID NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
            from_widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
            to_widget_id UUID NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
            from_anchor VARCHAR(10) NOT NULL,
            to_anchor VARCHAR(10) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Create indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_widget_connections_dashboard_id 
        ON widget_connections(dashboard_id);
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_widget_connections_from_to 
        ON widget_connections(from_widget_id, to_widget_id);
    """)


def downgrade() -> None:
    op.drop_table('widget_connections')
