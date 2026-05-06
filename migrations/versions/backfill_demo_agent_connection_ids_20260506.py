"""Backfill ``connection_ids`` on demo agents that were seeded with an empty array.

Lucas's 2026-05-06 QA: every demo visitor's three seeded agents
(Revenue Pulse / Customer Health Watch / Operations Radar) failed
``Run now`` with HTTP 400 because the agents had ``connection_ids=[]``.

Root cause was in ``DemoService._ensure_dataset_connections``: it called
``self.db.add(SpaceConnection(...))`` but never flushed before returning,
and ``AsyncSessionLocal`` runs with ``autoflush=False``. The next
function in the same transaction (``_seed_demo_agents``) ran a SELECT on
``space_connections`` that did not see the pending inserts, so
``primary_conn`` fell back to ``None``.

The code fix (explicit ``flush`` at the end of
``_ensure_dataset_connections``) lands in the same commit. This
migration backfills the rows that were already provisioned wrong:

  - find every Agent row where
      scope = 'space'
      AND scope_id maps to a Space whose ``is_demo`` = TRUE
      AND connection_ids = '{}' (empty array)
  - set its ``connection_ids`` to the first ``space_connections.connection_id``
    bound to that Space, if any exists

Idempotent: agents that already have a connection are untouched, and
demos that genuinely have no bound connections (shouldn't happen but
not catastrophic) are also untouched.

Revision ID: backfill_demo_agent_conn_ids_20260506
Revises: widget_source_20260505
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "backfill_demo_agent_conn_ids_20260506"
down_revision = "widget_source_20260505"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Defensive: skip silently if any of the involved tables is missing
    # (e.g. a fresh test DB that hasn't run earlier migrations).
    for required in ("agents", "spaces", "space_connections"):
        if not inspector.has_table(required):
            return

    # Postgres-only path (production target). The agent.scope_id column is
    # a string holding a UUID, so we cast it to UUID when joining with
    # spaces.id. We pick the first connection deterministically by
    # ordering on space_connections.id (insertion order, stable).
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                UPDATE agents AS a
                SET connection_ids = ARRAY[sc.connection_id]
                FROM spaces AS s,
                     LATERAL (
                         SELECT connection_id
                         FROM space_connections
                         WHERE space_id = s.id
                         ORDER BY id
                         LIMIT 1
                     ) AS sc
                WHERE a.scope = 'space'
                  AND a.scope_id::uuid = s.id
                  AND s.is_demo = TRUE
                  AND (a.connection_ids IS NULL OR a.connection_ids = '{}')
                """
            )
        )
    else:
        # SQLite path (test backend). connection_ids is stored as JSON
        # text via the array_with_sqlite_variant helper.
        rows = bind.execute(
            sa.text(
                """
                SELECT a.id AS agent_id, sc.connection_id AS connection_id
                FROM agents a
                JOIN spaces s ON a.scope_id = s.id
                JOIN space_connections sc ON sc.space_id = s.id
                WHERE a.scope = 'space'
                  AND s.is_demo = 1
                  AND (a.connection_ids IS NULL OR a.connection_ids = '[]')
                ORDER BY a.id, sc.id
                """
            )
        ).fetchall()
        seen: set[str] = set()
        for row in rows:
            agent_id = str(row.agent_id)
            if agent_id in seen:
                continue
            seen.add(agent_id)
            bind.execute(
                sa.text("UPDATE agents SET connection_ids = :ids WHERE id = :aid"),
                {
                    "ids": f'["{row.connection_id}"]',
                    "aid": agent_id,
                },
            )


def downgrade() -> None:
    # No safe downgrade — once we've populated connection_ids we can't
    # know which rows were originally empty vs intentionally set. The
    # backfill is data-only and idempotent, so it stays applied.
    pass
