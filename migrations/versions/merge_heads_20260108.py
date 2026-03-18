"""Merge Alembic heads: add_ai_tables + add_auth0_fields

Revision ID: merge_heads_20260108
Revises: add_ai_tables, add_auth0_fields
Create Date: 2026-01-08

This is a merge migration to unify multiple heads into a single linear head.
It intentionally performs no schema changes.
"""

from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = "merge_heads_20260108"
down_revision = ("add_ai_tables", "add_auth0_fields")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: merge migration
    pass


def downgrade() -> None:
    pass
    # No-op: merge migration
    pass
