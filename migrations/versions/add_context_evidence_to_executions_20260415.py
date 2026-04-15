"""Context evidence trail on agent_executions — Phase 2.6.

Each run records the exact set of context_documents it retrieved. The
IDs survive soft-delete of the underlying documents because
context_documents rows are never hard-deleted, so past runs remain
explainable even after a goal or widget disappears.

Revision ID: ctx_evidence_20260415
Revises: ctx_docs_20260415
Create Date: 2026-04-15 08:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "ctx_evidence_20260415"
down_revision = "ctx_docs_20260415"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    if pg:
        op.add_column(
            "agent_executions",
            sa.Column(
                "context_doc_ids",
                sa.dialects.postgresql.ARRAY(sa.dialects.postgresql.UUID(as_uuid=True)),
                nullable=False,
                server_default=sa.text("'{}'::uuid[]"),
            ),
        )
        op.add_column(
            "agent_executions",
            sa.Column(
                "context_intent",
                sa.String(32),
                nullable=True,
            ),
        )
    else:
        # SQLite test bed — JSON stands in for array.
        op.add_column(
            "agent_executions",
            sa.Column("context_doc_ids", sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        )
        op.add_column(
            "agent_executions",
            sa.Column("context_intent", sa.String(32), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agent_executions", "context_intent")
    op.drop_column("agent_executions", "context_doc_ids")
