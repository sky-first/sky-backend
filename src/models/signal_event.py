import uuid
from sqlalchemy import Column, String, Text, DateTime, JSON, Enum as SQLEnum
import enum
from datetime import datetime

from src.config.database import Base

class SignalCategory(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    TRENDS = "trends"

class SignalNature(str, enum.Enum):
    EVENT = "Event"
    SIGNAL = "Signal"
    HYPOTHESIS = "Hypothesis"

class SignalConfidence(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"

class SignalEvent(Base):
    """
    Represents a signal, event, or trend manually added by the user
    in the Signals & Events settings menu.
    """
    __tablename__ = "signal_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    category = Column(SQLEnum(SignalCategory), nullable=False)
    sub_type = Column(String(100), nullable=False)
    nature = Column(SQLEnum(SignalNature), nullable=False, default=SignalNature.EVENT)
    description = Column(Text, nullable=False)
    
    start_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    impact_date = Column(DateTime, nullable=True)
    confidence = Column(SQLEnum(SignalConfidence), nullable=False, default=SignalConfidence.MEDIUM)
    
    # Store relations cleanly inside a JSON field 
    # { "product": "...", "kpi": "...", "client": "..." }
    relations = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Note: Depending on your exact schema needs, if these events need to trace back to a specific workspace
    # or user, you might want to add a `workspace_id` or `user_id` here. For now it's global as per the UI.
