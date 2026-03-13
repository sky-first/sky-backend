"""add_crew_id_to_semantic_cache

Revision ID: add_sc_crew_id
Revises: merge_metrics_head_20260225
Create Date: 2026-03-10

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_sc_crew_id"
down_revision = "merge_metrics_head_20260225"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure vector extension exists - Removed to avoid pgvector dependency
    # op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "semantic_cache" not in tables:
        op.create_table(
            "semantic_cache",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("connection_id", sa.String(), nullable=False),
            sa.Column("space_id", sa.String(), nullable=True),
            sa.Column("crew_id", sa.String(), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_semantic_cache_connection_id", "semantic_cache", ["connection_id"], unique=False)
        op.create_index("ix_semantic_cache_space_id", "semantic_cache", ["space_id"], unique=False)
        op.create_index("ix_semantic_cache_crew_id", "semantic_cache", ["crew_id"], unique=False)
    else:
        # If table already exists, just add the missing crew_id column
        columns = [col["name"] for col in inspector.get_columns("semantic_cache")]
        if "crew_id" not in columns:
            op.add_column("semantic_cache", sa.Column("crew_id", sa.String(), nullable=True))
            op.create_index("ix_semantic_cache_crew_id", "semantic_cache", ["crew_id"], unique=False)


def downgrade() -> None:
    op.drop_table("semantic_cache")
