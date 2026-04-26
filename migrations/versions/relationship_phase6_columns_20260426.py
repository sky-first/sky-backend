"""Add Phase 6 N↔N columns to user_enterprise_relationships.

Knowledge refactor Phase 6. Adds: targets, keys, ai_inferred,
confidence, scope, scope_id. Existing single-target columns stay so
the Phase 5 callers keep working.

Revision ID: relationship_phase6_columns_20260426
Revises: glossary_phase5_columns_20260426
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "relationship_phase6_columns_20260426"
down_revision = "glossary_phase5_columns_20260426"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    (
        "targets",
        sa.Column(
            "targets",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    ),
    (
        "keys",
        sa.Column(
            "keys",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    ),
    (
        "ai_inferred",
        sa.Column(
            "ai_inferred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    ),
    ("confidence", sa.Column("confidence", sa.Numeric(), nullable=True)),
    ("scope", sa.Column("scope", sa.String(length=20), nullable=True)),
    ("scope_id", sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("user_enterprise_relationships")}
    for name, column in _NEW_COLUMNS:
        if name not in cols:
            op.add_column("user_enterprise_relationships", column)


def downgrade() -> None:
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("user_enterprise_relationships", name)
