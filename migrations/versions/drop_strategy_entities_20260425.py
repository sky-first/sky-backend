"""Drop Strategy entities (Knowledge refactor — Phase 1a).

Pillar / Objective / OKR / Initiative / KeyResult / Assumption / Cycle
all collapse into Metric attributes (target_value, threshold, tags) in
Phase 2. We're pre-launch with no real customer data, so dropping the
tables outright is safe.

The matching SQLAlchemy models, services, routes, and tests were
removed in the same PR; this migration aligns the database with the
new code surface.

Revision ID: drop_strategy_entities_20260425
Revises: platform_branding_20260425
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "drop_strategy_entities_20260425"
down_revision = "platform_branding_20260425"
branch_labels = None
depends_on = None


# Strategy module tables. Listed in reverse-FK order so child tables go
# first. M2M junction tables (``strategy_initiative_crews`` /
# ``strategy_initiative_spaces``) point to ``strategy_initiatives`` and
# must drop *before* it.
#
# ``CASCADE`` on the eventual metric/glossary FKs is intentionally NOT
# used here — we want any unexpected FK to fail loudly so the operator
# notices code drift before the migration runs in prod.
_STRATEGY_TABLES = [
    # Junction tables first — their FKs point to the main tables below.
    "strategy_initiative_spaces",
    "strategy_initiative_crews",
    # Main entity tables, child → parent order.
    "strategy_key_results",
    "strategy_assumptions",
    "strategy_initiatives",
    "strategy_okrs",
    "strategic_objectives",
    "strategic_pillars",
    "strategy_cycles",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # First pass — anything that prefix-matches "strategy_" or
    # "strategic_" but isn't in our known list is almost certainly a
    # junction table we forgot. Drop them before touching the main
    # entity tables. Catches future drift if a m2m gets added without
    # updating this list.
    known = set(_STRATEGY_TABLES)
    for tbl in sorted(existing):
        if (tbl.startswith("strategy_") or tbl.startswith("strategic_")) and tbl not in known:
            op.drop_table(tbl)

    # Second pass — drop in the explicit reverse-FK order above.
    # Re-fetch the table list because the first pass changed it.
    existing = set(sa.inspect(bind).get_table_names())
    for tbl in _STRATEGY_TABLES:
        if tbl in existing:
            op.drop_table(tbl)


def downgrade() -> None:
    # Intentionally a no-op. The Strategy schema is gone for good — Phase 2
    # is the forward path; "downgrade" would be a redesign, not a rollback.
    # Leaving the body empty so an accidental ``alembic downgrade`` doesn't
    # silently re-create empty tables that the new code can't populate.
    raise NotImplementedError(
        "Strategy entities were removed in the Knowledge refactor. "
        "There is no safe downgrade path — see "
        "sky-security/docs/KNOWLEDGE_REFACTOR.md."
    )
