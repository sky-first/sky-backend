"""add_knowledge_library_tables

Revision ID: e6e9eef87b74
Revises: agent_selected_context_20260423
Create Date: 2026-04-24 11:46:25.714811

Idempotent: in some local environments knowledge_files / knowledge_file_chunks
were created by an earlier autoflush/SQLAlchemy create_all path before this
migration ran. Re-running here would crash with DuplicateTable. We guard
each DDL with inspector checks so re-applying is safe.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "e6e9eef87b74"
down_revision = "agent_selected_context_20260423"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(table))


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── knowledge_files ────────────────────────────────────────────────────────
    if not _table_exists("knowledge_files"):
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
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    for ix_name, ix_cols in [
        ("ix_knowledge_files_user_id", ["user_id"]),
        ("ix_knowledge_files_scope", ["scope", "scope_id"]),
        ("ix_knowledge_files_status", ["status"]),
        ("ix_knowledge_files_alive", ["deleted_at"]),
    ]:
        if not _index_exists("knowledge_files", ix_name):
            op.create_index(ix_name, "knowledge_files", ix_cols)

    # ── knowledge_file_chunks ──────────────────────────────────────────────────
    if not _table_exists("knowledge_file_chunks"):
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
            sa.Column("embedding", Vector(768), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if not _index_exists("knowledge_file_chunks", "ix_knowledge_chunks_file_chunk"):
        op.create_index(
            "ix_knowledge_chunks_file_chunk",
            "knowledge_file_chunks",
            ["file_id", "chunk_index"],
            unique=True,
        )
    if not _index_exists("knowledge_file_chunks", "ix_knowledge_chunks_embedding"):
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_embedding "
            "ON knowledge_file_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )

    # ── knowledge_quota_usages (atomic per-scope quota row) ────────────────────
    if not _table_exists("knowledge_quota_usages"):
        op.create_table(
            "knowledge_quota_usages",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("scope", sa.String(16), nullable=False),
            sa.Column("scope_id", UUID(as_uuid=True), nullable=False),
            sa.Column("bytes_used", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("files_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if not _index_exists("knowledge_quota_usages", "ix_quota_usages_scope"):
        op.create_index(
            "ix_quota_usages_scope",
            "knowledge_quota_usages",
            ["scope", "scope_id"],
            unique=True,
        )

    # ── link context_documents → knowledge_files ───────────────────────────────
    if not _column_exists("context_documents", "knowledge_file_id"):
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
    if _column_exists("context_documents", "knowledge_file_id"):
        op.drop_column("context_documents", "knowledge_file_id")
    if _table_exists("knowledge_quota_usages"):
        op.drop_table("knowledge_quota_usages")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding")
    if _table_exists("knowledge_file_chunks"):
        op.drop_table("knowledge_file_chunks")
    if _table_exists("knowledge_files"):
        op.drop_table("knowledge_files")
