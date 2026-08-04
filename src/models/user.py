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
    LargeBinary,
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
        default="member",
        server_default="member",
    )  # super_admin, admin, member (legacy aliases: owner, user)
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

    # Sky Support operator flag
    is_sky_operator = Column(Boolean, nullable=False, default=False, server_default="false")
    # Internal hierarchy on the Sky platform itself — ``ceo``, ``admin``,
    # ``support`` or ``read_only``. Independent of ``role`` above, which
    # is the tenant-side role (owner / admin / member of a customer
    # workspace). Null for customer users; set only when
    # ``is_sky_operator`` is True. The Console gates features by this
    # value via :func:`src.api.console_auth.role_for`.
    sky_role = Column(String(20), nullable=True)

    # Public demo guest (Cenário B). is_demo=true marks users provisioned
    # via /demo/signup; the cleanup cron uses demo_expires_at to decide
    # whether the user (and its Space, dashboards, chats) is past TTL and
    # can be deleted. Demo users have a placeholder password_hash and
    # cannot log in via /auth/login — only via the JWT issued at signup.
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    demo_expires_at = Column(DateTime(timezone=True), nullable=True)

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

    # Password reset (forgot-password / reset-password flow).
    # A urlsafe token minted by ``POST /auth/forgot-password`` and cleared
    # the moment ``POST /auth/reset-password`` consumes it (or it expires).
    # Mirrors the invite-token columns above: nullable, short-lived, and
    # only set for tenants that allow password auth. SSO-only tenants
    # never populate these — the endpoints 403 before minting.
    password_reset_token = Column(String(255), nullable=True, index=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)

    # SSO Metadata
    sso_metadata = Column(JSON, nullable=True)  # Store provider-specific data

    # Multi-Factor Authentication (TOTP — Phase 3).
    # ``mfa_enabled`` gates the second-factor branch in the login
    # service. The secret + recovery codes are Fernet-encrypted with
    # ENCRYPTION_KEY at the service layer (see src/services/mfa_service.py)
    # so a DB-only leak does not expose working TOTP seeds. Recovery
    # codes are stored as bcrypt hashes inside the encrypted JSON
    # payload — single-use, single-show.
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    mfa_secret_encrypted = Column(LargeBinary, nullable=True)
    mfa_recovery_codes_encrypted = Column(LargeBinary, nullable=True)
    mfa_enrolled_at = Column(DateTime(timezone=True), nullable=True)
    mfa_last_used_at = Column(DateTime(timezone=True), nullable=True)

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
    owned_pages = relationship("Page", back_populates="owner", foreign_keys="Page.owner_id")
    page_memberships = relationship("PageMember", back_populates="user")
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
        Index(
            "idx_users_password_reset_token",
            "password_reset_token",
            postgresql_where=password_reset_token.isnot(None),
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
    # BE-05 (Sky Mobile) — the login lineage this token belongs to. A fresh
    # login opens a new family; every rotation stays in the same family. If a
    # revoked token is ever replayed we revoke the whole family (reuse =
    # theft). Nullable for backfill: old rows are each their own family
    # (family_id == id), resolved via ``family_id or id`` at read time.
    family_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
        Index("idx_refresh_tokens_token", "token"),
        Index("idx_refresh_tokens_expires_at", "expires_at"),
        Index("idx_refresh_tokens_family_id", "family_id"),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id})>"
