"""Dashboard and widget models."""

import uuid

from sqlalchemy import  (
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


class Dashboard(Base):
    """Dashboard model."""

    __tablename__ = "dashboards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    planet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id = Column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    canvas_settings = Column(JSON, nullable=True)  # {scale, position, snapToGrid, gridSize}
    is_locked = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    planet = relationship("Planet", back_populates="dashboards")
    widgets = relationship("Widget", back_populates="dashboard", cascade="all, delete-orphan")
    connections = relationship(
        "Connection", back_populates="dashboard", cascade="all, delete-orphan"
    )
    template = relationship("Template", foreign_keys=[template_id])

    __table_args__ = (
        Index("idx_dashboards_planet_id", "planet_id", postgresql_where=deleted_at.is_(None)),
        Index("idx_dashboards_created_by", "created_by", postgresql_where=deleted_at.is_(None)),
        Index("idx_dashboards_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Dashboard(id={self.id}, name={self.name}, planet_id={self.planet_id})>"


class Widget(Base):
    """Widget model."""

    __tablename__ = "widgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(50), nullable=False)  # chart, kpi, table, ai-box, text
    title = Column(String(255), nullable=False)
    position = Column(JSON, nullable=False)  # {x, y}
    size = Column(JSON, nullable=False)  # {width, height}
    data = Column(JSON, nullable=True)  # Widget-specific data
    config = Column(JSON, nullable=True)  # Styling and configuration
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
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )

    # Relationships
    dashboard = relationship("Dashboard", back_populates="widgets")
    connection = relationship("DataConnection", foreign_keys=[connection_id])
    query = relationship("AIQuery", foreign_keys=[query_id])

    __table_args__ = (
        Index("idx_widgets_dashboard_id", "dashboard_id"),
        Index("idx_widgets_type", "type"),
        Index("idx_widgets_connection_id", "connection_id"),
        Index("idx_widgets_query_id", "query_id"),
    )

    def __repr__(self) -> str:
        return f"<Widget(id={self.id}, type={self.type}, title={self.title})>"


class Connection(Base):
    """Widget connection model (connections between widgets)."""

    __tablename__ = "widget_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
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
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    dashboard = relationship("Dashboard", back_populates="connections")
    from_widget = relationship("Widget", foreign_keys=[from_widget_id])
    to_widget = relationship("Widget", foreign_keys=[to_widget_id])

    __table_args__ = (
        Index("idx_widget_connections_dashboard_id", "dashboard_id"),
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
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
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
