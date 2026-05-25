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
    # Thread state (added in chat-threads-master-plan PR1, 2026-05-20).
    # resolved_at: owner or page-editor closed the thread (/resolve).
    # pinned_message_id: message highlighted at top of the thread (/pin).
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    pinned_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    # The `foreign_keys` is required because Conversation also points at
    # messages.id via pinned_message_id (chat-threads PR1), so SQLAlchemy
    # can no longer infer which FK relates the parent/child collection.
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        foreign_keys="Message.conversation_id",
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
    # ``kind`` further partitions the user/assistant axis along the
    # collaborative-thread semantics (chat-threads-master-plan PR1,
    # 2026-05-20):
    #   - question     → owner's prompt that fires AI
    #   - ai_response  → LLM reply
    #   - comment      → non-owner discussion (does NOT fire AI)
    #   - system       → pin/resolve/transfer audit events
    kind = Column(String(20), nullable=True)
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
    # Threading + AI-bundling (chat-threads-master-plan PR1, 2026-05-20).
    # parent_message_id: a reply to a comment points at the comment;
    # an ai_response points at the triggering question.
    # incorporated_in_message_id: when a comment was bundled into an
    # Ask-AI call, set to the resulting ai_response id; FE renders
    # "incorporated in AI response #N" badges from this.
    parent_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    incorporated_in_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships — the `foreign_keys` disambiguates against the
    # parent_message_id / incorporated_in_message_id self-FKs added in
    # chat-threads PR1 (otherwise SQLAlchemy can't infer which FK pairs
    # parent ↔ child for the messages collection).
    conversation = relationship(
        "Conversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role_valid",
        ),
        CheckConstraint(
            "kind IS NULL OR kind IN ('question', 'ai_response', 'comment', 'system')",
            name="ck_messages_kind_valid",
        ),
        Index(
            "idx_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, conv={self.conversation_id}, role={self.role})>"
