"""Add ``viz_kind`` column to ``agent_findings`` so the Pulse FE can
render a coherent card variant + matching widget kind end-to-end.

Sprint 1.17 round 5 (Lucas 2026-05-15): "se eu criar um agente agora
e obter uma resposta a resposta virá assim já? voce precisa garantir
que sim". The FE was deciding the visualisation by hashing the
finding id — fine for the legacy data but it meant a brand-new agent
output never had an authoritative format. Now the agent picks a
``viz_kind`` (one of bar / pie / line / donut / kpi / big_number /
delta / range / heatmap / sparkline / text / list) when it produces
the finding, the API persists it on this column, and the FE renders
the matching shape. The toolbar chart picker uses the same key when
the user pins the insight, so the resulting widget is consistent
with what the card promised.

Idempotent + backwards-compatible: NULL means "legacy, fall back to
the FE hash picker", so no backfill is required.

Revision ID: agent_finding_viz_kind_20260515
Revises: backfill_demo_agent_conn_ids_20260506
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "agent_finding_viz_kind_20260515"
down_revision = "backfill_demo_agent_conn_ids_20260506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("agent_findings")]
    if "viz_kind" in cols:
        return
    op.add_column(
        "agent_findings",
        sa.Column("viz_kind", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("agent_findings")]
    if "viz_kind" not in cols:
        return
    op.drop_column("agent_findings", "viz_kind")
