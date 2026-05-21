"""ChangeRequest model — chat ↔ widget bridge.

A non-owner comment referencing a widget (#N mention or selected-widget
context) creates a change_request row pointing at the widget. The
widget owner sees an "X pending changes" pill; accepting re-runs AI
with the comment as additional context, dismissing closes it silently.

See chat-threads-master-plan PR3 for the full design.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class ChangeRequest(Base):
    """A user request to change a widget, originating in a chat comment."""

    __tablename__ = "change_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Lifecycle. Default 'pending'; transitions to accepted / dismissed
    # via the widget owner. The status varchar (not a PG enum) is so
    # adding new states later is a code change, not a schema migration.
    status = Column(
        String(20), nullable=False, server_default="pending"
    )
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'dismissed')",
            name="ck_change_requests_status_valid",
        ),
        Index(
            "idx_change_requests_widget_pending",
            "widget_id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "idx_change_requests_conversation",
            "conversation_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ChangeRequest(id={self.id}, widget={self.widget_id}, "
            f"status={self.status})>"
        )
