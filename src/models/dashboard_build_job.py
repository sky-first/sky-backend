"""Dashboard build job model (async dashboard generation)."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class DashboardBuildJob(Base):
    """
    Tracks an async dashboard build running in background (Celery).

    The frontend polls this table (via API) to show progress and know when
    the dashboard is ready.
    """

    __tablename__ = "dashboard_build_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Context (useful for debugging and for the worker task)
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    goal = Column(String(255), nullable=False)
    language = Column(String(8), nullable=False, server_default="en")
    max_widgets = Column(Integer, nullable=False, server_default="8")

    status = Column(String(20), nullable=False, server_default="queued", index=True)
    total_widgets = Column(Integer, nullable=False, server_default="0")
    completed_widgets = Column(Integer, nullable=False, server_default="0")

    dashboard_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Optional: ids of widgets already created (for idempotency / progressive UI)
    created_widget_ids = Column(JSON, nullable=True)

    # Optional: store planner output for debugging / retries
    plan = Column(JSON, nullable=True)

    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_dashboard_build_jobs_user_status", "user_id", "status"),
        Index("idx_dashboard_build_jobs_created_at", "created_at"),
    )
