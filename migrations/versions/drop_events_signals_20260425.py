"""Drop Events / Signals (Knowledge refactor — Phase 1b).

SignalEvent (signal_events) and IntelligenceSignal (intelligence_signals)
are not part of the new Knowledge model — Sources + Knowledge +
Relationships are the only first-class concepts. Agent-emitted findings
move into the Pulse halo + Universe Intelligence and ride the existing
agent_findings table; macro / external feeds will be re-introduced in a
later phase as a thin "ingested_signal" table without the legacy
multi-category enum machinery.

We're pre-launch with no real customer data, so dropping outright is
safe — same posture as the Phase 1a Strategy drop.

Revision ID: drop_events_signals_20260425
Revises: drop_strategy_entities_20260425
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "drop_events_signals_20260425"
down_revision = "drop_strategy_entities_20260425"
branch_labels = None
depends_on = None


# Order doesn't matter much here (these tables are independent of each
# other), but we drop ``intelligence_signals`` first to keep alphabetic
# parity with the Phase 1a migration's reverse-FK style.
_EVENT_TABLES = [
    "intelligence_signals",
    "signal_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for tbl in _EVENT_TABLES:
        if tbl in existing:
            op.drop_table(tbl)


def downgrade() -> None:
    # Same posture as Phase 1a — Events/Signals are gone for good. Phase 2+
    # may add a slim ``ingested_signal`` table, but that is a different
    # schema from what we just dropped, so a "downgrade" would silently
    # diverge from prod truth. Fail loudly instead.
    raise NotImplementedError(
        "Events / Signals were removed in the Knowledge refactor (Phase 1b). "
        "There is no safe downgrade path — see "
        "sky-security/docs/KNOWLEDGE_REFACTOR.md."
    )
