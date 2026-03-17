"""Add metrics column to data_connections

Revision ID: add_metrics_20260225
Revises: fix_missing_tables_20260123
Create Date: 2026-02-25 11:19:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_metrics_20260225"
down_revision = "fix_missing_tables_20260123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    has_column = False
    for col in inspector.get_columns("data_connections"):
        if col["name"] == "metrics":
            has_column = True
            break

    if not has_column:
        op.add_column(
            "data_connections",
            sa.Column("metrics", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("data_connections", "metrics")
