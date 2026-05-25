"""Phase 6 — connection tier + agent auditable_only mode

Adds two columns and the CHECK constraints that gate Phase 6's runtime
filter: agents that opt into `auditable_only` mode skip any data
connection whose `tier` is more sensitive than `internal`.

Connection tier semantics (lowest to highest sensitivity):
  - internal       — default, freely usable by autonomous agents
  - confidential   — agents may not query unless run by an owner
  - restricted     — only owner/admin platform principals may query

Agent.auditable_only:
  - false (default) — agent may query every connection it has access to
  - true            — agent runtime drops every connection whose tier
                      is not 'internal' before issuing the query

Idempotent: rerunning the migration is a no-op if the columns are
already present.

Revision ID: connection_tier_agent_auditable_20260501
Revises: resource_acl_crew_principal_20260501
"""

from alembic import op
import sqlalchemy as sa


revision = "connection_tier_agent_auditable_20260501"
down_revision = "resource_acl_crew_principal_20260501"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchall()
    return bool(rows)


def upgrade() -> None:
    if not _column_exists("data_connections", "tier"):
        op.add_column(
            "data_connections",
            sa.Column(
                "tier",
                sa.String(length=20),
                nullable=False,
                server_default="internal",
            ),
        )
        op.execute(
            "ALTER TABLE data_connections "
            "DROP CONSTRAINT IF EXISTS ck_data_connections_tier"
        )
        op.create_check_constraint(
            "ck_data_connections_tier",
            "data_connections",
            "tier IN ('internal','confidential','restricted')",
        )

    if not _column_exists("agents", "auditable_only"):
        op.add_column(
            "agents",
            sa.Column(
                "auditable_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if _column_exists("agents", "auditable_only"):
        op.drop_column("agents", "auditable_only")
    if _column_exists("data_connections", "tier"):
        op.execute(
            "ALTER TABLE data_connections "
            "DROP CONSTRAINT IF EXISTS ck_data_connections_tier"
        )
        op.drop_column("data_connections", "tier")
