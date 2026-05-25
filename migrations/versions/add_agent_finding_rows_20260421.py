"""Add rows JSONB to agent_findings — structured tabular result set.

Lets the InsightCockpit render Bar/Line/Pie/Table charts straight from
the finding without going back to the AI service. Shape: `{"columns":
[...], "data": [[...], ...], "truncated": bool?}`.

Revision ID: agent_finding_rows_20260421
Revises: space_table_hidden_cols_20260420
Create Date: 2026-04-21 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "agent_finding_rows_20260421"
down_revision = "space_table_hidden_cols_20260420"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    jsonb_type = sa.dialects.postgresql.JSONB if pg else sa.JSON

    op.add_column(
        "agent_findings",
        sa.Column(
            "rows",
            jsonb_type,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_findings", "rows")
