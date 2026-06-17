"""preserve agent findings/executions on agent delete (CASCADE -> SET NULL)

Deleting an agent used to CASCADE-delete every row in agent_findings and
agent_executions, erasing the insights the agent had produced. Product
decision: an agent delete must keep that history — the rows are detached
(agent_id -> NULL) instead of removed. Insights already added to a page are
independent widgets and survive regardless; this preserves the finding/
execution history too.

Switches both FKs from ON DELETE CASCADE to ON DELETE SET NULL and makes
agent_id nullable. The ORM side drops its delete-orphan cascade and uses
passive_deletes so the DB performs the SET NULL.

Revision ID: agent_findings_set_null_20260617
Revises: reconcile_agent_counter_20260617
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "agent_findings_set_null_20260617"
down_revision = "reconcile_agent_counter_20260617"
branch_labels = None
depends_on = None

# table -> fk constraint name (Postgres default naming)
_FKS = {
    "agent_findings": "agent_findings_agent_id_fkey",
    "agent_executions": "agent_executions_agent_id_fkey",
}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table, fk in _FKS.items():
        if table not in existing:
            continue
        op.drop_constraint(fk, table, type_="foreignkey")
        op.alter_column(
            table,
            "agent_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        op.create_foreign_key(
            fk, table, "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table, fk in _FKS.items():
        if table not in existing:
            continue
        op.drop_constraint(fk, table, type_="foreignkey")
        # Detached rows (agent_id IS NULL) would violate NOT NULL on downgrade.
        # Remove them so the column can be made non-nullable again.
        op.execute(sa.text(f"DELETE FROM {table} WHERE agent_id IS NULL"))
        op.alter_column(
            table,
            "agent_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
        op.create_foreign_key(
            fk, table, "agents", ["agent_id"], ["id"], ondelete="CASCADE"
        )
