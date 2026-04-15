"""Context Layer (Phase 2.1) — add context_documents table.

This is the foundation of the agent brain described in
`docs/agent-and-ai-master-plan.md` §3.6. Every domain entity
(connections/tables/columns, business rules, events, relationships,
platform fabric, and outputs) will be projected into this table as a
vectorised, RBAC-scoped document, enabling retrieval across the entire
organisational context in a single query.

The embedding column uses the pgvector extension (already in
`requirements.txt` since inception but never activated — we enable it
here). Dimension 1536 matches OpenAI `text-embedding-3-small` and
equivalent open-weights models (bge-small reports 384, so we allow NULL
for future dimension-aware embedding providers to write narrower rows
via a separate column — out of scope for this migration).

Revision ID: ctx_docs_20260415
Revises: widgets_uniq_pin_20260414
Create Date: 2026-04-15 06:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "ctx_docs_20260415"
down_revision = "widgets_uniq_pin_20260414"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    pg = _is_postgres()

    # Only try to enable the extension on Postgres. Tests run on SQLite.
    if pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "context_documents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36), nullable=False),
        sa.Column("source_table", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "metadata_jsonb",
            sa.dialects.postgresql.JSONB if pg else sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if pg else sa.text("'{}'"),
        ),
        sa.Column("space_id", sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("crew_id", sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36), sa.ForeignKey("crews.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_user_id", sa.dialects.postgresql.UUID(as_uuid=True) if pg else sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="space"),
        sa.Column(
            "pii_flags",
            sa.dialects.postgresql.ARRAY(sa.String) if pg else sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::text[]") if pg else sa.text("'[]'"),
        ),
        sa.Column("language", sa.String(8), nullable=False, server_default="pt"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ("
            "'connection','table','column',"
            "'pillar','goal','okr','initiative','risk','kpi','glossary',"
            "'event_internal','event_external','event_trend','event_macro',"
            "'relationship',"
            "'user','role','space','crew','membership',"
            "'pin','widget','insight','conversation','message','like'"
            ")",
            name="ck_context_documents_kind",
        ),
        sa.CheckConstraint(
            "visibility in ('public','space','crew','user')",
            name="ck_context_documents_visibility",
        ),
    )

    # embedding column — only on Postgres. Tests skip the vector column.
    if pg:
        op.execute(
            "ALTER TABLE context_documents "
            "ADD COLUMN embedding vector(1536) NULL"
        )

    # Indexes
    op.create_index(
        "ix_context_documents_source",
        "context_documents",
        ["source_table", "source_id"],
        unique=True,
    )
    op.create_index(
        "ix_context_documents_scope",
        "context_documents",
        ["space_id", "crew_id", "kind"],
    )
    op.create_index(
        "ix_context_documents_kind",
        "context_documents",
        ["kind"],
    )
    op.create_index(
        "ix_context_documents_alive",
        "context_documents",
        ["deleted_at"],
    )

    if pg:
        # Full-text index over title || body (Portuguese dictionary; fallback
        # to simple dictionary when content is non-PT — documented in §3.6).
        op.execute(
            "CREATE INDEX ix_context_documents_fts ON context_documents "
            "USING GIN (to_tsvector('portuguese', title || ' ' || body))"
        )
        # HNSW index on embedding — cheap to build, fast ANN retrieval.
        # m=16, ef_construction=64 match pgvector defaults and are adequate
        # for the scale we are targeting at POC (< 1M rows per space).
        op.execute(
            "CREATE INDEX ix_context_documents_embedding ON context_documents "
            "USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    pg = _is_postgres()

    if pg:
        op.execute("DROP INDEX IF EXISTS ix_context_documents_embedding")
        op.execute("DROP INDEX IF EXISTS ix_context_documents_fts")
    op.drop_index("ix_context_documents_alive", table_name="context_documents")
    op.drop_index("ix_context_documents_kind", table_name="context_documents")
    op.drop_index("ix_context_documents_scope", table_name="context_documents")
    op.drop_index("ix_context_documents_source", table_name="context_documents")
    op.drop_table("context_documents")
    # We intentionally do NOT drop the `vector` extension — other tables
    # (future or existing dev DB state) may still depend on it.
