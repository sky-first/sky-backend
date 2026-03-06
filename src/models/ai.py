"""AI-related models."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class AIQuery(Base):
    """AI query model."""

    __tablename__ = "ai_queries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    data_sample = Column(JSON, nullable=True)  # Sample data from query (max 15 rows)
    sql = Column(Text, nullable=True)  # Generated SQL query
    status = Column(
        String(50), nullable=False, default="processing", server_default="processing"
    )  # processing, completed, error
    configure_data = Column(JSON, nullable=False)  # ConfigureData structure
    pipeline_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="SET NULL"),
        nullable=True,
    )
    planet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User")
    widget = relationship("Widget", foreign_keys=[widget_id])
    planet = relationship("Planet")

    __table_args__ = (
        Index("idx_ai_queries_user_id", "user_id"),
        Index("idx_ai_queries_widget_id", "widget_id"),
        Index("idx_ai_queries_planet_id", "planet_id"),
        Index("idx_ai_queries_status", "status"),
        Index("idx_ai_queries_created_at", "created_at"),
        Index("idx_ai_queries_planet_created", "planet_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AIQuery(id={self.id}, user_id={self.user_id}, status={self.status})>"


class AIHistory(Base):
    """AI history model."""

    __tablename__ = "ai_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query = Column(Text, nullable=False)
    preview = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    date = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    tags = Column(JSON, nullable=False, default=list, server_default="[]")
    category = Column(String(50), nullable=True)  # Finance, Marketing, Sales, General, Logistics
    pinned = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    planet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Collaborative context: used to scope history by active crew/space
    space_id = Column(String, nullable=True, index=True)
    crew_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    user = relationship("User")
    planet = relationship("Planet")

    __table_args__ = (
        Index("idx_ai_history_user_id", "user_id"),
        Index("idx_ai_history_planet_id", "planet_id"),
        Index("idx_ai_history_pinned", "pinned"),
        Index("idx_ai_history_category", "category"),
        Index("idx_ai_history_date", "date"),
        Index("idx_ai_history_user_date", "user_id", "date"),
        Index("idx_ai_history_planet_created", "planet_id", "created_at"),
        Index("idx_ai_history_crew_id", "crew_id"),
        Index("idx_ai_history_space_id", "space_id"),
    )

    def __repr__(self) -> str:
        return f"<AIHistory(id={self.id}, user_id={self.user_id}, category={self.category})>"


class Pipeline(Base):
    """Pipeline model."""

    __tablename__ = "pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        String(50), nullable=False, default="processing", server_default="processing"
    )  # processing, completed, error
    steps = Column(JSON, nullable=False, default=list, server_default="[]")  # Array of PipelineStep
    current_step = Column(String(255), nullable=True)
    errors = Column(JSON, nullable=True)  # Array of errors
    logs = Column(Text, nullable=True)
    started_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    query_rel = relationship("AIQuery", foreign_keys=[query_id])

    __table_args__ = (
        Index("idx_pipelines_query_id", "query_id"),
        Index("idx_pipelines_status", "status"),
        Index("idx_pipelines_started_at", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<Pipeline(id={self.id}, query_id={self.query_id}, status={self.status})>"


class PipelineStep:
    """Pipeline step (embedded in JSON)."""

    def __init__(
        self,
        id: str,
        name: str,
        kind: str,  # question, orchestrator, project, sql, tables, answer
        status: str,  # COMPLETED, PROCESSING, PENDING, ERROR
        content: str,
        logs: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.kind = kind
        self.status = status
        self.content = content
        self.logs = logs
        self.started_at = started_at
        self.completed_at = completed_at


class ChatMessage(Base):
    """Chat message model."""

    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(50), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    planet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    widget = relationship("Widget")
    planet = relationship("Planet")

    __table_args__ = (
        Index("idx_chat_messages_widget_id", "widget_id"),
        Index("idx_chat_messages_planet_id", "planet_id"),
        Index("idx_chat_messages_timestamp", "timestamp"),
        Index("idx_chat_messages_planet_created", "planet_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, widget_id={self.widget_id}, type={self.type})>"


class AIResponse(Base):
    """AI response model."""

    __tablename__ = "ai_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    widget = relationship("Widget")

    __table_args__ = (
        Index("idx_ai_responses_widget_id", "widget_id"),
        Index("idx_ai_responses_is_active", "is_active"),
        Index("idx_ai_responses_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AIResponse(id={self.id}, widget_id={self.widget_id}, is_active={self.is_active})>"


class AIFeedback(Base):
    """User feedback for an AI query (good/bad + optional comment)."""

    __tablename__ = "ai_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating = Column(String(10), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    query = relationship("AIQuery", foreign_keys=[query_id])
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint("rating IN ('good', 'bad')", name="ck_ai_feedback_rating"),
        UniqueConstraint("query_id", "user_id", name="uq_ai_feedback_query_user"),
        Index("idx_ai_feedback_query_id", "query_id"),
        Index("idx_ai_feedback_user_id", "user_id"),
        Index("idx_ai_feedback_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AIFeedback(id={self.id}, query_id={self.query_id}, user_id={self.user_id}, rating={self.rating})>"
