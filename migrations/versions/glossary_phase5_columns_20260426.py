"""Add Phase 5 columns to glossary_terms.

Knowledge refactor Phase 5. Adds the 4-scope columns + aliases +
related_metric_ids + related_source_ids + status + certified_* +
created_by_user_id. Existing space_id/crew_id columns stay so legacy
callers keep working during the migration window.

Revision ID: glossary_phase5_columns_20260426
Revises: promotion_tables_20260426
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "glossary_phase5_columns_20260426"
down_revision = "promotion_tables_20260426"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    ("scope", sa.Column("scope", sa.String(length=20), nullable=True)),
    ("scope_id", sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True)),
    ("slug", sa.Column("slug", sa.String(length=255), nullable=True)),
    (
        "status",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    ),
    (
        "aliases",
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    ),
    (
        "related_metric_ids",
        sa.Column(
            "related_metric_ids",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    ),
    (
        "related_source_ids",
        sa.Column(
            "related_source_ids",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    ),
    (
        "certified_by_user_id",
        sa.Column(
            "certified_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ),
    (
        "certified_at",
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=True),
    ),
    (
        "created_by_user_id",
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("glossary_terms")}
    for name, column in _NEW_COLUMNS:
        if name not in cols:
            op.add_column("glossary_terms", column)
    new_indexes = {idx["name"] for idx in inspector.get_indexes("glossary_terms")}
    if "ix_glossary_terms_scope" not in new_indexes:
        op.create_index("ix_glossary_terms_scope", "glossary_terms", ["scope"])
    if "ix_glossary_terms_scope_id" not in new_indexes:
        op.create_index("ix_glossary_terms_scope_id", "glossary_terms", ["scope_id"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_scope_id", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_scope", table_name="glossary_terms")
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("glossary_terms", name)
