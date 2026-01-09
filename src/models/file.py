"""File upload and sync log models."""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class FileUpload(Base):
    """File upload model."""

    __tablename__ = "file_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False, index=True)
    size = Column(BigInteger, nullable=False)  # bytes
    url = Column(Text, nullable=False)
    storage = Column(String(50), nullable=False)  # s3, local, gcs
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parsed_data = Column(JSON, nullable=True)  # Parsed data (CSV, Excel, etc.)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()", index=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User")
    widget = relationship("Widget")

    __table_args__ = (
        Index("idx_file_uploads_user_id", "user_id"),
        Index("idx_file_uploads_widget_id", "widget_id"),
        Index("idx_file_uploads_mime_type", "mime_type"),
        Index("idx_file_uploads_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<FileUpload(id={self.id}, filename={self.filename}, mime_type={self.mime_type})>"


class SyncLog(Base):
    """Sync log model."""

    __tablename__ = "sync_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(50), nullable=False)  # success, error
    records_synced = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)  # milliseconds
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default="now()", index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    # Relationships
    connection = relationship("DataConnection")

    __table_args__ = (
        Index("idx_sync_logs_connection_id", "connection_id"),
        Index("idx_sync_logs_started_at", "started_at"),
        Index("idx_sync_logs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SyncLog(id={self.id}, connection_id={self.connection_id}, status={self.status})>"
