"""Add ai_tone, ai_style, ai_context to user preferences

Revision ID: 4dbc97e72355
Revises: ee8c60ac46f7
Create Date: 2026-01-23 11:02:48.488217

"""

# revision identifiers, used by Alembic.
revision = "4dbc97e72355"
down_revision = "ee8c60ac46f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is a JSON column, so we don't need a schema change.
    # We are using this migration to mark the point where we start using 'ai_tone', 'ai_style', and 'ai_context' keys.
    pass


def downgrade() -> None:
    # No schema change to revert.
    pass
