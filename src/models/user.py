"""User and authentication models."""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class User(Base):
    """User model."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    avatar = Column(Text, nullable=True)
    role = Column(
        String(50),
        nullable=False,
        default="user",
        server_default="user",
    )  # admin, user, viewer
    email_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    onboarding_step = Column(Integer, nullable=True, default=0, server_default="0")
    onboarding_version = Column(Integer, nullable=False, default=0, server_default="0")
    has_completed_onboarding = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    selected_domain = Column(String(255), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        String(50),
        nullable=False,
        default="offline",
        server_default="offline",
    )  # active, away, offline
    preferences = Column(JSON, nullable=True, default={}, server_default=text("'{}'"))

    # Auth0 Integration
    auth0_id = Column(String(255), unique=True, nullable=True, index=True)
    auth_provider = Column(
        String(50), nullable=False, default="local", server_default="local"
    )  # local, auth0, google, azure, okta
    auth_provider_id = Column(String(255), nullable=True, index=True)

    # Invite System
    invite_token = Column(String(255), nullable=True, index=True)
    invite_expires_at = Column(DateTime(timezone=True), nullable=True)
    invited_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # SSO Metadata
    sso_metadata = Column(JSON, nullable=True)  # Store provider-specific data

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    owned_planets = relationship("Planet", back_populates="owner", foreign_keys="Planet.owner_id")
    planet_memberships = relationship("PlanetMember", back_populates="user")
    owned_workspaces = relationship(
        "Workspace", back_populates="owner", foreign_keys="Workspace.owner_id"
    )
    workspace_memberships = relationship("WorkspaceMember", back_populates="user")
    starred_items = relationship("StarredItem", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_users_email", "email", postgresql_where=deleted_at.is_(None)),
        Index("idx_users_role", "role", postgresql_where=deleted_at.is_(None)),
        Index("idx_users_created_at", "created_at"),
        Index("idx_users_auth0_id", "auth0_id", postgresql_where=deleted_at.is_(None)),
        Index(
            "idx_users_auth_provider",
            "auth_provider",
            postgresql_where=deleted_at.is_(None),
        ),
        Index(
            "idx_users_invite_token",
            "invite_token",
            postgresql_where=invite_token.isnot(None),
        ),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class RefreshToken(Base):
    """Refresh token model."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = Column(
        Text, nullable=False, unique=True, index=True
    )  # Changed from String(255) to Text for JWT tokens
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
        Index("idx_refresh_tokens_token", "token"),
        Index("idx_refresh_tokens_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id})>"
