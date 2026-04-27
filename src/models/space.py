"""Space model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite has no native JSONB — fall back to JSON in tests so the column
# still round-trips. Same pattern used by src/models/context_document.py.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class Space(Base):
    """Space model."""

    __tablename__ = "spaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(7), nullable=True)  # Hex color
    icon = Column(String(255), nullable=True)
    privacy = Column(
        String(50), nullable=False, default="private", server_default="private"
    )  # public, private
    sensitivity = Column(
        String(50), nullable=False, default="internal", server_default="internal"
    )  # internal, confidential, restricted
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Public demo (Cenário B). When is_demo=true the cron at
    # cleanup_expired_demo_spaces uses demo_expires_at to decide whether
    # the sandbox is past its TTL and can be CASCADE-deleted with
    # everything inside it (members, dashboards, widgets, chats).
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    demo_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    crews = relationship("Crew", back_populates="space", cascade="all, delete-orphan")
    space_connections = relationship(
        "SpaceConnection", back_populates="space", cascade="all, delete-orphan"
    )
    space_tables = relationship("SpaceTable", back_populates="space", cascade="all, delete-orphan")
    members = relationship("SpaceMember", back_populates="space", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_spaces_created_by", "created_by", postgresql_where=deleted_at.is_(None)),
    )

    def __repr__(self) -> str:
        return f"<Space(id={self.id}, name={self.name})>"


class SpaceConnection(Base):
    """Space-Connection association table."""

    __tablename__ = "space_connections"

    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # Relationships
    space = relationship("Space", back_populates="space_connections")
    connection = relationship("DataConnection")

    __table_args__ = (
        Index("idx_space_connections_space_id", "space_id"),
        Index("idx_space_connections_connection_id", "connection_id"),
    )

    def __repr__(self) -> str:
        return f"<SpaceConnection(space_id={self.space_id}, connection_id={self.connection_id})>"


class SpaceMember(Base):
    """Space member model."""

    __tablename__ = "space_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Per-space role — distinct from the platform-wide `users.role`.
    # Valid values: admin | navigator | explorer. A platform `owner`
    # or `admin` bypasses this column in RBACService, so the field
    # only matters for platform `member` users who need scoped
    # privileges. See docs/rbac-two-axis-design.md for the full
    # permission matrix.
    role = Column(
        String(20),
        nullable=False,
        default="navigator",
        server_default="navigator",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    space = relationship("Space", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        Index(
            "idx_space_members_space_user",
            "space_id",
            "user_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<SpaceMember(space_id={self.space_id}, user_id={self.user_id})>"


class SpaceTable(Base):
    """Space specific table association."""

    __tablename__ = "space_tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=True)
    # Columns that the Space chose to HIDE from this table. Empty list means
    # every column is visible (default). The connection itself still owns
    # the full schema — hidden_columns is a per-space filter applied on
    # retrieval and render, not on storage.
    hidden_columns = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    space = relationship("Space", back_populates="space_tables")
    connection = relationship("DataConnection")

    __table_args__ = (
        Index(
            "idx_space_tables_space_conn_table",
            "space_id",
            "connection_id",
            "table_name",
            "schema_name",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<SpaceTable(space_id={self.space_id}, table={self.table_name})>"
