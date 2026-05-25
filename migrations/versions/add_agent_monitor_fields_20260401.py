"""Add monitor_type, custom_sql, table_ids, last_answer to agents + answer, sql_executed to executions

Revision ID: add_agent_monitor_fields_20260401
Revises: create_agents_20260401
Create Date: 2026-04-01 19:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "agent_monitor_20260401"
down_revision = "create_agents_20260401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agents table — new fields
    op.add_column("agents", sa.Column("monitor_type", sa.String(20), nullable=False, server_default="question"))
    op.add_column("agents", sa.Column("custom_sql", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("table_ids", sa.ARRAY(sa.String()), nullable=True))
    op.add_column("agents", sa.Column("last_answer", sa.Text(), nullable=True))

    # Agent executions table — new fields
    op.add_column("agent_executions", sa.Column("answer", sa.Text(), nullable=True))
    op.add_column("agent_executions", sa.Column("sql_executed", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_executions", "sql_executed")
    op.drop_column("agent_executions", "answer")
    op.drop_column("agents", "last_answer")
    op.drop_column("agents", "table_ids")
    op.drop_column("agents", "custom_sql")
    op.drop_column("agents", "monitor_type")
