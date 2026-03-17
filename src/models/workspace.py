"""Workspace models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Workspace(Base):
    """Workspace model."""

    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # personal, team
    color = Column(String(7), nullable=False)  # Hex color
    icon = Column(String(255), nullable=True)
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    is_active = Column(Boolean, nullable=False, default=False, server_default="false")
    last_accessed = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship(
        "User", foreign_keys=[owner_id], back_populates="owned_workspaces"
    )
    members = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    # Note: Dashboards are related to Planets, not Workspaces directly

    __table_args__ = (
        Index(
            "idx_workspaces_owner_id", "owner_id", postgresql_where=deleted_at.is_(None)
        ),
        Index("idx_workspaces_type", "type", postgresql_where=deleted_at.is_(None)),
        Index(
            "idx_workspaces_is_active",
            "is_active",
            postgresql_where=deleted_at.is_(None),
        ),
        Index("idx_workspaces_last_accessed", "last_accessed"),
    )

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, name={self.name}, type={self.type})>"


class WorkspaceMember(Base):
    """Workspace member model."""

    __tablename__ = "workspace_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
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
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")

    __table_args__ = (
        Index(
            "idx_workspace_members_workspace_user",
            "workspace_id",
            "user_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<WorkspaceMember(workspace_id={self.workspace_id}, user_id={self.user_id}, role={self.role})>"
