"""Add selected_context JSONB to agents.

Holds the agent's explicit selection across every Universe Intelligence
category: Business Rules (pillars/objectives/okrs/initiatives/
assumptions/key_results/glossary_terms), Events (signal_events,
intelligence_signals), Relationships (enterprise_relationships),
Outputs (widgets, insights, pages). Empty arrays / missing keys mean
"no filter — include everything the RAG can see in scope".

Revision ID: agent_selected_context_20260423
Revises: personal_owner_user_id_20260422
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "agent_selected_context_20260423"
down_revision = "personal_owner_user_id_20260422"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "selected_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "selected_context")
