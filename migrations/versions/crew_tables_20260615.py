"""create crew_tables (per-crew dataset/table scoping)

Adds the ``crew_tables`` association table so a crew can be restricted to
specific tables of a connection it has access to (mirrors ``space_tables`` one
level down). The ``crew_connections`` table already exists; this completes the
per-crew data-access model used by the crew-creation flow.

Revision ID: crew_tables_20260615
Revises: password_reset_cols_20260614
Create Date: 2026-06-15

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "crew_tables_20260615"
# Chains after the current staging head (password_reset) so the alembic
# history stays linear — `chat_sessions_20260609` had become a branchpoint
# once staging merged the notif-i18n / password-reset migrations.
down_revision = "password_reset_cols_20260614"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "crew_tables" not in tables:
        op.create_table(
            "crew_tables",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "crew_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("crews.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "connection_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("data_connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("schema_name", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_crew_tables_crew_id", "crew_tables", ["crew_id"], unique=False)
        op.create_index(
            "ix_crew_tables_connection_id",
            "crew_tables",
            ["connection_id"],
            unique=False,
        )
        op.create_index(
            "idx_crew_tables_crew_conn_table",
            "crew_tables",
            ["crew_id", "connection_id", "table_name", "schema_name"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "crew_tables" in tables:
        op.drop_index("idx_crew_tables_crew_conn_table", table_name="crew_tables")
        op.drop_index("ix_crew_tables_connection_id", table_name="crew_tables")
        op.drop_index("ix_crew_tables_crew_id", table_name="crew_tables")
        op.drop_table("crew_tables")
