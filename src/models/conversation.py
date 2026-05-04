"""Conversation and Message models — the first-class Q&A thread.

A conversation is the persistent thread a user navigates. It is scoped to a
page (always) and optionally to a space / crew for collaborative contexts.
Widgets/insights reference back to the conversation (and the specific message)
they were pinned from, so the user can always re-enter the thread that
produced an insight with full history.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Conversation(Base):
    """A Q&A thread scoped to a page (and optionally a space/crew)."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, page_id={self.page_id}, title={self.title})>"


class Message(Base):
    """One message within a conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'system'
    content = Column(Text, nullable=False)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_queries.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 4), nullable=True)
    # Insights-Analytics — see src/services/insights_tier.py.
    tier = Column(String(2), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    pinned_widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role_valid",
        ),
        Index(
            "idx_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, conv={self.conversation_id}, role={self.role})>"
