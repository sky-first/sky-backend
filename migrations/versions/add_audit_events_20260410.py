"""Add audit_events table with hash chain and append-only triggers.

Revision ID: add_audit_events_20260410
Revises: add_crew_id_to_pages_20260410
Create Date: 2026-04-10 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

revision = "add_audit_events_20260410"
down_revision = "add_crew_id_to_pages_20260410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_kind", sa.String(50), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_kind", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ip", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("sky_session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sky_ticket_id", sa.String(100), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("this_hash", sa.String(64), nullable=False),
    )

    op.create_index("idx_audit_actor", "audit_events", ["actor_id", sa.text("occurred_at DESC")])
    op.create_index("idx_audit_action", "audit_events", ["action", sa.text("occurred_at DESC")])
    op.create_index("idx_audit_resource", "audit_events", ["resource_kind", "resource_id"])
    op.create_index("idx_audit_occurred", "audit_events", [sa.text("occurred_at DESC")])

    # Trigger: prevent UPDATE on audit_events
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_prevent_update()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: UPDATE is not allowed';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_audit_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_prevent_update();
    """)

    # Trigger: prevent DELETE on audit_events
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_prevent_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: DELETE is not allowed';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_audit_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_prevent_delete();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_delete ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_prevent_delete()")
    op.execute("DROP FUNCTION IF EXISTS audit_prevent_update()")
    op.drop_index("idx_audit_occurred", table_name="audit_events")
    op.drop_index("idx_audit_resource", table_name="audit_events")
    op.drop_index("idx_audit_action", table_name="audit_events")
    op.drop_index("idx_audit_actor", table_name="audit_events")
    op.drop_table("audit_events")
