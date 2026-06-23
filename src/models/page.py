"""Page models.

A Page is the canonical "thing you're looking at" in the canvas: a
container with its own widgets, canvas settings, and (when shared) a
member list. The old Dashboard concept was folded into this model
in 2026-05-20 — every page IS the canvas.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Page(Base):
    """Page model — the single canvas container."""

    __tablename__ = "pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # personal, team
    color = Column(String(7), nullable=False)  # Hex color
    icon = Column(String(255), nullable=True)
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        comment="Set = crew-level page (only crew members see)",
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        comment="Set = space-level page (all space members see, no crew required)",
    )

    # ─── Canvas state (absorbed from the former Dashboard model) ────────────
    canvas_settings = Column(
        JSON,
        nullable=True,
        comment="Canvas viewport: {scale, position, snapToGrid, gridSize}",
    )
    is_locked = Column(Boolean, nullable=False, default=False, server_default="false")
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active = Column(Boolean, nullable=False, default=False, server_default="false")
    # Exactly one canonical page per crew (and per space-level scope): the
    # shared "room" every member converges on so live cursors/websockets work.
    # Enforced by partial unique indexes (see migration) + the ensure_default_*
    # services. The canonical page cannot be deleted.
    is_canonical = Column(Boolean, nullable=False, default=False, server_default="false")
    last_accessed = Column(DateTime(timezone=True), nullable=True)
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

    # ─── Relationships ─────────────────────────────────────────────────────
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_pages")
    members = relationship("PageMember", back_populates="page", cascade="all, delete-orphan")
    widgets = relationship("Widget", back_populates="page", cascade="all, delete-orphan")
    widget_connections = relationship(
        "Connection", back_populates="page", cascade="all, delete-orphan"
    )
    template = relationship("Template", foreign_keys=[template_id])

    __table_args__ = (
        Index("idx_pages_owner_id", "owner_id", postgresql_where=deleted_at.is_(None)),
        Index("idx_pages_type", "type", postgresql_where=deleted_at.is_(None)),
        Index("idx_pages_is_active", "is_active", postgresql_where=deleted_at.is_(None)),
        Index("idx_pages_last_accessed", "last_accessed"),
    )

    def __repr__(self) -> str:
        return f"<Page(id={self.id}, name={self.name}, type={self.type})>"


class PageMember(Base):
    """Page member model."""

    __tablename__ = "page_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(50), nullable=False)  # owner, admin, member, viewer
    joined_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    page = relationship("Page", back_populates="members")
    user = relationship("User", back_populates="page_memberships")

    __table_args__ = (
        Index(
            "idx_page_members_page_user",
            "page_id",
            "user_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<PageMember(page_id={self.page_id}, user_id={self.user_id}, role={self.role})>"
