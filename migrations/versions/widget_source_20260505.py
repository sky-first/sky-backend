"""Add ``source`` column to widgets so audit can distinguish AI-synthesized from manual.

Lucas's 2026-05-05 audit asked: "alguém de backend consegue ir na API
e de fato ver que foi gerada automaticamente e não foi feita por IA
mesmo?". Today the answer is "no" — the Widget row's ``created_by``
is the user (because Create Analysis runs in the user's session) and
there is no flag separating a manual chart from one synthesised by
the AI from a refusal answer (mock fallback). This migration adds a
``source`` enum column so the same question can be answered with a
SQL filter:

  - ``manual``       — user dropped a widget on the canvas
  - ``ai_synthesis`` — Create Analysis on a real AI answer
                       (data_sample / SQL plan / chosen_table present)
  - ``mock_fallback`` — Create Analysis fired on a refusal/empty
                        answer (the bug Lucas hit)
  - ``agent``         — emitted by an autonomous agent run

Idempotent / backwards-compatible. NULL means legacy/unknown. The
column is plain VARCHAR (not a Postgres enum) so adding new values
later is a code change, not a schema migration.

Revision ID: widget_source_20260505
Revises: insights_tier_20260504
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "widget_source_20260505"
down_revision = "insights_tier_20260504"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("widgets") and not _has_column(
        inspector, "widgets", "source"
    ):
        op.add_column(
            "widgets",
            sa.Column("source", sa.String(length=20), nullable=True),
        )
        op.create_index(
            "idx_widgets_source",
            "widgets",
            ["source"],
            postgresql_where=sa.text("source IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "widgets", "source"):
        try:
            op.drop_index("idx_widgets_source", table_name="widgets")
        except Exception:
            pass
        op.drop_column("widgets", "source")
