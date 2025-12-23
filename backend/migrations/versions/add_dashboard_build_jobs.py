"""Add dashboard_build_jobs table

Revision ID: add_dashboard_build_jobs
Revises: add_user_datasets
Create Date: 2025-12-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_dashboard_build_jobs"
down_revision = "add_user_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_build_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("goal", sa.String(255), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("max_widgets", sa.Integer, nullable=False, server_default="8"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("total_widgets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_widgets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dashboard_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_widget_ids", postgresql.JSON, nullable=True),
        sa.Column("plan", postgresql.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["planet_id"], ["planets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connection_id"], ["data_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"], ondelete="SET NULL"),
    )

    op.create_index("idx_dashboard_build_jobs_user_id", "dashboard_build_jobs", ["user_id"], unique=False)
    op.create_index("idx_dashboard_build_jobs_planet_id", "dashboard_build_jobs", ["planet_id"], unique=False)
    op.create_index("idx_dashboard_build_jobs_space_id", "dashboard_build_jobs", ["space_id"], unique=False)
    op.create_index("idx_dashboard_build_jobs_connection_id", "dashboard_build_jobs", ["connection_id"], unique=False)
    op.create_index("idx_dashboard_build_jobs_dashboard_id", "dashboard_build_jobs", ["dashboard_id"], unique=False)
    op.create_index("idx_dashboard_build_jobs_status", "dashboard_build_jobs", ["status"], unique=False)
    op.create_index(
        "idx_dashboard_build_jobs_user_status",
        "dashboard_build_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index("idx_dashboard_build_jobs_created_at", "dashboard_build_jobs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_dashboard_build_jobs_created_at", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_user_status", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_status", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_dashboard_id", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_connection_id", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_space_id", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_planet_id", table_name="dashboard_build_jobs")
    op.drop_index("idx_dashboard_build_jobs_user_id", table_name="dashboard_build_jobs")
    op.drop_table("dashboard_build_jobs")

