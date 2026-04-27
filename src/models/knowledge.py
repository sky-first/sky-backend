"""Knowledge Library models — knowledge_files, chunks, quota."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from src.config.database import Base


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    blob_path = Column(Text, nullable=True)
    sha256_hash = Column(String(64), nullable=True)

    # Scope: personal | crew | space
    scope = Column(String(16), nullable=False, default="personal")
    scope_id = Column(UUID(as_uuid=True), nullable=True)

    # Processing pipeline: pending | processing | ready | error
    status = Column(String(16), nullable=False, default="pending")
    processing_error = Column(Text, nullable=True)
    chunks_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    chunks = relationship(
        "KnowledgeFileChunk",
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_knowledge_files_user_id", "user_id"),
        Index("ix_knowledge_files_scope", "scope", "scope_id"),
        Index("ix_knowledge_files_status", "status"),
        Index("ix_knowledge_files_alive", "deleted_at"),
    )


class KnowledgeFileChunk(Base):
    __tablename__ = "knowledge_file_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=False, default=0)
    embedding = Column(Vector(768), nullable=True)  # pgvector — must match AI service dimension
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    file = relationship("KnowledgeFile", back_populates="chunks")

    __table_args__ = (
        Index("ix_knowledge_chunks_file_chunk", "file_id", "chunk_index", unique=True),
    )


class KnowledgeQuotaUsage(Base):
    """One row per (scope, scope_id) pair — locked via SELECT FOR UPDATE on quota checks."""

    __tablename__ = "knowledge_quota_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(16), nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=False)
    bytes_used = Column(BigInteger, nullable=False, default=0)
    files_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_quota_usages_scope", "scope", "scope_id", unique=True),
    )
