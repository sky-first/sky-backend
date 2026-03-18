"""create templates table

Revision ID: fd74af4b3c14
Revises: dbb9a0420d3e
Create Date: 2026-03-18 16:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "fd74af4b3c14"
down_revision = "dbb9a0420d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create templates table
    op.create_table(
        "templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("creator", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("widgets", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("icon", sa.String(255), nullable=True),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("popular", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enterprise", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. Add indexes to templates
    op.create_index("idx_templates_category", "templates", ["category"])
    op.create_index("idx_templates_popular", "templates", ["popular"])
    op.create_index("idx_templates_enterprise", "templates", ["enterprise"])

    # 3. Add foreign key to dashboards
    op.create_foreign_key(
        "fk_dashboards_templates",
        "dashboards",
        "templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    
    # 4. Add index for template_id in dashboards for performance
    op.create_index("idx_dashboards_template_id", "dashboards", ["template_id"])


def downgrade() -> None:
    # 1. Remove index from dashboards
    op.drop_index("idx_dashboards_template_id", "dashboards")

    # 2. Remove foreign key from dashboards
    op.drop_constraint("fk_dashboards_templates", "dashboards", type_="foreignkey")

    # 3. Drop templates table
    op.drop_table("templates")
