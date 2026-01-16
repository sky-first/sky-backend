"""Notification models."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class NotificationType(str, Enum):
    """Notification types."""
    
    SYSTEM = "system"
    ALERT = "alert"
    INSIGHT = "insight"
    SHARE = "share"
    MENTION = "mention"
    ACCESS = "access"


class Notification(Base):
    """Notification model."""

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Notification Details
    type = Column(String(50), nullable=False)  # Enum value from NotificationType
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Linked Entity (for deep linking and context)
    entity_type = Column(String(50), nullable=False)  # e.g., 'dashboard', 'insight'
    entity_id = Column(String(255), nullable=False)
    deep_link = Column(String(500), nullable=True)
    
    # Status
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")

    # Relationships
    user = relationship("User", backref="notifications")

    __table_args__ = (
        Index("idx_notifications_user_unread", "user_id", "is_read"),
    )

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.type}, title={self.title})>"
