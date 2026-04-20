"""Add glossary_terms table — business vocabulary for the context layer.

Glossary terms are the 8th category orbiting the sun in Universe
Intelligence. A term is a short definition (GMV, MAU, Churn, …) scoped
to a Space / Crew. Terms are projected into ``context_documents`` with
kind=``glossary`` via the standard context-event emitter so retrieval
can cite them alongside strategy and connections.

Revision ID: glossary_terms_20260418
Revises: ai_duration_20260415
Create Date: 2026-04-18 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "glossary_terms_20260418"
down_revision = "ai_duration_20260415"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()
    uuid_col = sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36)

    op.create_table(
        "glossary_terms",
        sa.Column("id", uuid_col, primary_key=True),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "space_id",
            uuid_col,
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "crew_id",
            uuid_col,
            sa.ForeignKey("crews.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "owner_user_id",
            uuid_col,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("space_id", "crew_id", "term", name="uq_glossary_scope_term"),
    )
    op.create_index("ix_glossary_terms_space", "glossary_terms", ["space_id"])
    op.create_index("ix_glossary_terms_crew", "glossary_terms", ["crew_id"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_crew", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_space", table_name="glossary_terms")
    op.drop_table("glossary_terms")
