"""add_knowledge_library_tables

Revision ID: e6e9eef87b74
Revises: agent_selected_context_20260423
Create Date: 2026-04-24 11:46:25.714811

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "e6e9eef87b74"
down_revision = "agent_selected_context_20260423"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension must exist (created by infra — see sky-poc-infra/terraform)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── knowledge_files ────────────────────────────────────────────────────────
    op.create_table(
        "knowledge_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("blob_path", sa.Text, nullable=True),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("scope_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("chunks_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_knowledge_files_user_id", "knowledge_files", ["user_id"])
    op.create_index("ix_knowledge_files_scope", "knowledge_files", ["scope", "scope_id"])
    op.create_index("ix_knowledge_files_status", "knowledge_files", ["status"])
    op.create_index("ix_knowledge_files_alive", "knowledge_files", ["deleted_at"])

    # ── knowledge_file_chunks ──────────────────────────────────────────────────
    # embedding is ARRAY[FLOAT8]; HNSW index added by AI colleague after model choice.
    op.create_table(
        "knowledge_file_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding", Vector(768), nullable=True),  # pgvector — 768 dims (nomic/OpenAI)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_file_chunk",
        "knowledge_file_chunks",
        ["file_id", "chunk_index"],
        unique=True,
    )
    # HNSW vector index for fast cosine similarity search
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding "
        "ON knowledge_file_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ── knowledge_quota_usages (atomic per-scope quota row) ────────────────────
    op.create_table(
        "knowledge_quota_usages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bytes_used", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("files_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_quota_usages_scope",
        "knowledge_quota_usages",
        ["scope", "scope_id"],
        unique=True,
    )

    # ── link context_documents → knowledge_files ───────────────────────────────
    op.add_column(
        "context_documents",
        sa.Column(
            "knowledge_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("context_documents", "knowledge_file_id")
    op.drop_table("knowledge_quota_usages")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding")
    op.drop_table("knowledge_file_chunks")
    op.drop_table("knowledge_files")
