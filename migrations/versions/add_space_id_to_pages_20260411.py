"""Add space_id to pages for space-level pages.

Pages can now belong to 4 scopes:
- Personal: space_id=NULL, crew_id=NULL (only owner sees)
- Space-level: space_id=X, crew_id=NULL (all space members see)
- Crew-level: space_id=NULL, crew_id=Y (only crew members see)
- Organization: space_id=NULL, crew_id=NULL, is_org_wide=true (everyone sees)

Revision ID: add_space_id_to_pages_20260411
Revises: add_is_sky_operator_20260411
Create Date: 2026-04-11 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_space_id_to_pages_20260411"
down_revision = "add_is_sky_operator_20260411"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pages",
        sa.Column(
            "space_id",
            UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_pages_space_id",
        "pages",
        ["space_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND space_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_pages_space_id", table_name="pages")
    op.drop_column("pages", "space_id")
