"""Notification model."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class NotificationType(str, Enum):
    """Notification types."""

    DASHBOARD_UPDATED = "DASHBOARD_UPDATED"
    NEW_INSIGHT_AVAILABLE = "NEW_INSIGHT_AVAILABLE"
    NEW_WIDGET_COMMENT = "NEW_WIDGET_COMMENT"
    COMMENT_MENTION = "COMMENT_MENTION"
    DASHBOARD_EDITED_BY_OTHER = "DASHBOARD_EDITED_BY_OTHER"
    METRIC_THRESHOLD_EXCEEDED = "METRIC_THRESHOLD_EXCEEDED"
    DASHBOARD_PERFORMANCE_DEGRADED = "DASHBOARD_PERFORMANCE_DEGRADED"


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
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type = Column(String(50), nullable=False)  # NotificationType enum value
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Entity reference (polymorphic-like)
    entity_type = Column(String(50), nullable=True)  # dashboard, widget, metric
    entity_id = Column(UUID(as_uuid=True), nullable=True)

    deep_link = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )

    # Relationships
    user = relationship("User", backref="notifications")
    space = relationship("Space")

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.type})>"
