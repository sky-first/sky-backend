"""Add service_principals table for crew-level agent identity.

Each Crew gets one auto-created service principal. Agents run as this
principal, not as the user who created them.

Revision ID: add_service_principals_20260410
Revises: add_audit_events_20260410
Create Date: 2026-04-10 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "add_service_principals_20260410"
down_revision = "add_audit_events_20260410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_principals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("crew_id", UUID(as_uuid=True), sa.ForeignKey("crews.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("permissions_snapshot", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_sp_crew", "service_principals", ["crew_id"])

    # Auto-create a service principal for each existing crew
    op.execute("""
        INSERT INTO service_principals (crew_id, name)
        SELECT id, 'sa-crew-' || LEFT(id::text, 8)
        FROM crews
        WHERE NOT EXISTS (
            SELECT 1 FROM service_principals sp WHERE sp.crew_id = crews.id
        )
    """)


def downgrade() -> None:
    op.drop_index("idx_sp_crew", table_name="service_principals")
    op.drop_table("service_principals")
