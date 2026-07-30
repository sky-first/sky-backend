"""Structured feed fields on agent_findings (BE-03, Sky Mobile).

The mobile Insights surface needs machine-readable findings: a sparkline
``series``, up-to-3 ``stat_tiles``, and a way to tell an autonomous *scan*
finding (no registered agent) from a normal *agent* finding. Adds:

* ``series``       jsonb  — [{t, v}] behind the headline number (may be [])
* ``stat_tiles``   jsonb  — [{label, value}] up to 3
* ``source``       text   — 'agent' | 'scan' (default 'agent')
* ``space_id``     uuid   — scope for scan findings (they have no agent_id)
* ``agent_name``   text   — display name for scan findings

Additive and backward-compatible: existing rows default to ``source='agent'``
and NULL for the rest, so the current agent-findings feed is unchanged.

Revision ID: agent_finding_structured_20260730
Revises: tenant_membership_20260730
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "agent_finding_structured_20260730"
down_revision = "tenant_membership_20260730"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_findings", sa.Column("series", JSONB(), nullable=True))
    op.add_column("agent_findings", sa.Column("stat_tiles", JSONB(), nullable=True))
    op.add_column(
        "agent_findings",
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'agent'"),
        ),
    )
    op.add_column("agent_findings", sa.Column("space_id", PG_UUID(as_uuid=True), nullable=True))
    op.add_column("agent_findings", sa.Column("agent_name", sa.String(length=255), nullable=True))
    op.create_index("idx_agent_findings_space_id", "agent_findings", ["space_id"])


def downgrade() -> None:
    op.drop_index("idx_agent_findings_space_id", table_name="agent_findings")
    op.drop_column("agent_findings", "agent_name")
    op.drop_column("agent_findings", "space_id")
    op.drop_column("agent_findings", "source")
    op.drop_column("agent_findings", "stat_tiles")
    op.drop_column("agent_findings", "series")
