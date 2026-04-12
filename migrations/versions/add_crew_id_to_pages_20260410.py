"""Add crew_id to pages for crew-scoped collaborative pages.

Pages with crew_id = a crew's UUID are collaborative pages visible to all
crew members. Pages with crew_id = NULL are personal pages visible only to
the owner.

Revision ID: add_crew_id_to_pages_20260410
Revises: merge_heads_20260406
Create Date: 2026-04-10 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers
revision = "add_crew_id_to_pages_20260410"
down_revision = "merge_heads_20260406"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pages",
        sa.Column(
            "crew_id",
            UUID(as_uuid=True),
            sa.ForeignKey("crews.id", ondelete="SET NULL"),
            nullable=True,
            comment="NULL = personal page; non-NULL = collaborative crew page",
        ),
    )
    op.create_index(
        "idx_pages_crew_id",
        "pages",
        ["crew_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND crew_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_pages_crew_id", table_name="pages")
    op.drop_column("pages", "crew_id")
