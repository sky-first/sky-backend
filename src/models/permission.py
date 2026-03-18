"""Permission and API key models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConnectionPermission(Base):
    """Connection permission model."""

    __tablename__ = "connection_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    access_level = Column(String(50), nullable=False)  # full, read-only, custom
    table_access = Column(
        JSON, nullable=True
    )  # Array of table names (if access_level = 'custom')
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    connection = relationship("DataConnection", back_populates="permissions")
    space = relationship("Space")
    crew = relationship("Crew")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "space_id",
            "crew_id",
            "user_id",
            name="uq_connection_permissions",
        ),
        Index("idx_connection_permissions_connection_id", "connection_id"),
        Index("idx_connection_permissions_space_id", "space_id"),
        Index("idx_connection_permissions_crew_id", "crew_id"),
        Index("idx_connection_permissions_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<ConnectionPermission(connection_id={self.connection_id}, access_level={self.access_level})>"


class TableMemberPermission(Base):
    """Table member permission model - granular permissions per table and crew member."""

    __tablename__ = "table_member_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_name = Column(
        String(255), nullable=False
    )  # Table name (e.g., "users", "orders")
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    member_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crew_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    has_access = Column(
        String(10), nullable=False, default="true", server_default="true"
    )  # "true" or "false"
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    connection = relationship("DataConnection")
    crew = relationship("Crew")
    member = relationship("CrewMember")

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "table_name",
            "member_id",
            name="uq_table_member_permissions",
        ),
        Index("idx_table_member_permissions_connection_id", "connection_id"),
        Index("idx_table_member_permissions_table_name", "table_name"),
        Index("idx_table_member_permissions_crew_id", "crew_id"),
        Index("idx_table_member_permissions_member_id", "member_id"),
    )

    def __repr__(self) -> str:
        return f"<TableMemberPermission(connection_id={self.connection_id}, table_name={self.table_name}, member_id={self.member_id}, has_access={self.has_access})>"


class APIKey(Base):
    """API key model."""

    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    key_hash = Column(
        String(255), nullable=False, unique=True, index=True
    )  # Hashed API key
    key_prefix = Column(String(20), nullable=False)  # First characters for display
    permissions = Column(JSON, nullable=True)  # Array of permissions
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index("idx_api_keys_user_id", "user_id"),
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, user_id={self.user_id})>"


class Integration(Base):
    """Integration model."""

    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False)  # slack, webhook, email, etc.
    config = Column(JSON, nullable=False)  # Integration configuration
    enabled = Column(String(10), nullable=False, default="true", server_default="true")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index("idx_integrations_user_id", "user_id"),
        Index("idx_integrations_type", "type"),
    )

    def __repr__(self) -> str:
        return f"<Integration(id={self.id}, name={self.name}, type={self.type}, user_id={self.user_id})>"


class RolePermission(Base):
    """Role permission model - stores permissions for custom roles (Commander, Navigator, Explorer, Guest)."""

    __tablename__ = "role_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role = Column(
        String(50), nullable=False, unique=True, index=True
    )  # commander, navigator, explorer, guest
    permissions = Column(
        JSON, nullable=False
    )  # Dictionary of permission keys and boolean values
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    __table_args__ = (Index("idx_role_permissions_role", "role"),)

    def __repr__(self) -> str:
        return f"<RolePermission(role={self.role}, permissions={self.permissions})>"
