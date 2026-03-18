import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class SignalCategory(str, enum.Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"
    TRENDS = "TRENDS"


class SignalNature(str, enum.Enum):
    EVENT = "EVENT"
    SIGNAL = "SIGNAL"
    HYPOTHESIS = "HYPOTHESIS"


class SignalConfidence(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SignalEvent(Base):
    """
    Represents a signal, event, or trend manually added by the user
    in the Signals & Events settings menu.
    """

    __tablename__ = "signal_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    category = Column(SQLEnum(SignalCategory), nullable=False)
    sub_type = Column(String(100), nullable=False)
    nature = Column(SQLEnum(SignalNature), nullable=False, default=SignalNature.EVENT)
    description = Column(Text, nullable=False)

    start_date = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    impact_date = Column(DateTime(timezone=True), nullable=True)
    confidence = Column(SQLEnum(SignalConfidence), nullable=False, default=SignalConfidence.MEDIUM)

    # Store relations cleanly inside a JSON field
    # { "product": "...", "kpi": "...", "client": "..." }
    relations = Column(JSON, nullable=True)

    space_id = Column(
        UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    crew_id = Column(
        UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True
    )

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Note: Depending on your exact schema needs, if these events need to trace back to a specific workspace
    # or user, you might want to add a `workspace_id` or `user_id` here. For now it's global as per the UI.
