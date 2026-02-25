"""Space model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


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
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

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
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

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
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

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
