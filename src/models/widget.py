"""Widget, WidgetConnection, WidgetFeedback models.

Renamed from ``dashboard.py`` (2026-05-20 consolidation) — the old
``Dashboard`` entity was collapsed into ``Page``. Widgets and
connections now hang directly off a page via ``page_id``.
"""

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
from sqlalchemy.orm import backref, relationship

from src.config.database import Base


class Widget(Base):
    """Widget model."""

    __tablename__ = "widgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(
        String(50), nullable=False
    )  # chart, kpi, table, ai-box, text, shape, infographic, insight
    title = Column(String(255), nullable=False)
    position = Column(JSON, nullable=False)  # {x, y}
    size = Column(JSON, nullable=False)  # {width, height}
    data = Column(JSON, nullable=True)  # Widget-specific data
    config = Column(JSON, nullable=True)  # Styling and configuration
    # Layer order. Higher = rendered on top. Client computes front/back as
    # max(z_index)+1 / min(z_index)-1 among peers on the same page.
    z_index = Column(Integer, nullable=False, default=0, server_default="0")
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    query_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_queries.id", ondelete="SET NULL"),
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
        onupdate=func.now(),
    )

    # --- Agent / conversation attribution (nullable for backward compat) ---
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    pinned_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_sp_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_principals.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Provenance — Lucas's 2026-05-05 audit asked for a way to tell a
    # manually-authored widget apart from one Create Analysis stamped
    # from an AI answer (and especially from one created when the AI
    # answer was a refusal / mock_fallback). NULL = legacy/unknown,
    # otherwise one of: 'manual', 'ai_synthesis', 'mock_fallback',
    # 'agent'. Keeping it as VARCHAR (not Postgres enum) so adding new
    # categories is a code change, not a migration.
    source = Column(String(20), nullable=True)

    # Relationships
    page = relationship("Page", back_populates="widgets")
    connection = relationship("DataConnection", foreign_keys=[connection_id])
    query = relationship("AIQuery", foreign_keys=[query_id])

    __table_args__ = (
        Index("idx_widgets_page_id", "page_id"),
        Index("idx_widgets_type", "type"),
        Index("idx_widgets_connection_id", "connection_id"),
        Index("idx_widgets_query_id", "query_id"),
        Index(
            "idx_widgets_conversation_id",
            "conversation_id",
            postgresql_where=text("conversation_id IS NOT NULL"),
        ),
        Index(
            "idx_widgets_created_by_agent_id",
            "created_by_agent_id",
            postgresql_where=text("created_by_agent_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Widget(id={self.id}, type={self.type}, title={self.title})>"


class Connection(Base):
    """Widget connection model (connections between widgets)."""

    __tablename__ = "widget_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_anchor = Column(String(10), nullable=False)  # top, right, bottom, left
    to_anchor = Column(String(10), nullable=False)  # top, right, bottom, left
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    page = relationship("Page", back_populates="widget_connections")
    from_widget = relationship("Widget", foreign_keys=[from_widget_id])
    to_widget = relationship("Widget", foreign_keys=[to_widget_id])

    __table_args__ = (
        Index("idx_widget_connections_page_id", "page_id"),
        Index("idx_widget_connections_from_to", "from_widget_id", "to_widget_id"),
    )

    def __repr__(self) -> str:
        return f"<Connection(id={self.id}, from={self.from_widget_id}, to={self.to_widget_id})>"


class WidgetFeedback(Base):
    """Widget feedback model (Like/Dislike votes)."""

    __tablename__ = "widget_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score = Column(
        Integer,
        nullable=False,
        comment="1 for like, -1 for dislike",
    )

    reason = Column(Text, nullable=True)
    context = Column(String(50), nullable=True)  # 'personal' or 'collaborative'
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

    # Relationships
    widget = relationship("Widget", backref=backref("feedback", cascade="all, delete-orphan"))
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("idx_widget_feedback_widget_user", "widget_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<WidgetFeedback(id={self.id}, widget={self.widget_id}, score={self.score})>"


# ─── Boolean import for the page-side relationship ─────────────────────────
# (Page model declares ``widgets`` and ``widget_connections`` back_populates
# to mirror these definitions; no extra exports needed.)
_ = Boolean  # silence "imported but unused" if any tooling complains
