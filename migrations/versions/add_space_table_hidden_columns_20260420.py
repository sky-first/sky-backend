"""Add hidden_columns to space_tables — per-space column visibility.

Lets a Space hide specific columns on a connection's table without
affecting other Spaces that share the same connection. The connection
owns the full schema; this column is applied on retrieval / render.

Revision ID: space_table_hidden_cols_20260420
Revises: glossary_terms_20260418
Create Date: 2026-04-20 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "space_table_hidden_cols_20260420"
down_revision = "glossary_terms_20260418"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    jsonb_type = sa.dialects.postgresql.JSONB if pg else sa.JSON
    default = sa.text("'[]'::jsonb") if pg else sa.text("'[]'")

    op.add_column(
        "space_tables",
        sa.Column(
            "hidden_columns",
            jsonb_type,
            nullable=False,
            server_default=default,
        ),
    )


def downgrade() -> None:
    op.drop_column("space_tables", "hidden_columns")
