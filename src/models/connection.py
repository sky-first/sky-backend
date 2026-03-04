"""Data connection models."""

import uuid
from datetime import datetime

# Forward reference for SyncLog
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import func, JSON, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base

if TYPE_CHECKING:
    pass


class DataConnection(Base):
    """Data connection model."""

    __tablename__ = "data_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    connector_id = Column(
        String(100), nullable=False
    )  # mysql, postgresql, mongodb, google-sheets, rest-api
    description = Column(Text, nullable=True)
    status = Column(
        String(50), nullable=False, default="inactive", server_default="inactive"
    )  # active, inactive, error
    config = Column(JSON, nullable=False)  # Encrypted credentials
    sync_frequency = Column(String(100), nullable=True)  # Cron expression
    last_sync = Column(DateTime(timezone=True), nullable=True)
    next_sync = Column(DateTime(timezone=True), nullable=True)
    last_metadata_update = Column(DateTime(timezone=True), nullable=True)
    error = Column(JSON, nullable=True)  # {message: string, timestamp: timestamp}
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    metrics = Column(JSON, nullable=True)  # Aggregated usage metrics
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    connection_metadata = relationship(
        "ConnectionMetadata",
        back_populates="connection",
        uselist=False,
        cascade="all, delete-orphan",
    )
    permissions = relationship(
        "ConnectionPermission", back_populates="connection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "idx_data_connections_connector_id",
            "connector_id",
            postgresql_where=deleted_at.is_(None),
        ),
        Index("idx_data_connections_status", "status", postgresql_where=deleted_at.is_(None)),
        Index(
            "idx_data_connections_created_by", "created_by", postgresql_where=deleted_at.is_(None)
        ),
        Index("idx_data_connections_last_sync", "last_sync"),
    )

    def __repr__(self) -> str:
        return f"<DataConnection(id={self.id}, name={self.name}, connector_id={self.connector_id})>"


class ConnectionMetadata(Base):
    """Connection metadata model."""

    __tablename__ = "connection_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tables = Column(JSON, nullable=True)  # Array of TableMetadata
    schemas = Column(JSON, nullable=True)  # Array of SchemaMetadata
    documents = Column(JSON, nullable=True)  # Array of DocumentMetadata
    endpoints = Column(JSON, nullable=True)  # Array of EndpointMetadata
    last_metadata_update = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    connection = relationship("DataConnection", back_populates="connection_metadata")

    __table_args__ = (Index("idx_connection_metadata_connection_id", "connection_id"),)

    def __repr__(self) -> str:
        return f"<ConnectionMetadata(connection_id={self.connection_id})>"


# Embedded models (stored as JSON in ConnectionMetadata)
class TableMetadata:
    """Table metadata (embedded in JSON)."""

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        row_count: Optional[int] = None,
        columns: Optional[List["ColumnMetadata"]] = None,
        last_updated: Optional[datetime] = None,
        health: str = "Healthy",  # Healthy, Stale, Broken
        usage_score: int = 0,  # 0-100
        tags: Optional[List[str]] = None,
    ):
        self.name = name
        self.schema = schema
        self.row_count = row_count
        self.columns = columns or []
        self.last_updated = last_updated
        self.health = health
        self.usage_score = usage_score
        self.tags = tags or []


class ColumnMetadata:
    """Column metadata (embedded in JSON)."""

    def __init__(
        self,
        name: str,
        type: str,
        nullable: bool = True,
        description: Optional[str] = None,
    ):
        self.name = name
        self.type = type
        self.nullable = nullable
        self.description = description
