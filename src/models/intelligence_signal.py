
import uuid
from enum import Enum
from sqlalchemy import Column, String, Text, JSON, DateTime, Float, ForeignKey, text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.config.database import Base

class IntelligenceCategory(str, Enum):
    NOW = "now"
    SMART = "smart"
    EXPLORE = "explore"

class IntelligenceSignal(Base):
    """
    Proactive AI-generated insights for Universe Intelligence.
    """
    __tablename__ = "intelligence_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    planet_id = Column(UUID(as_uuid=True), ForeignKey("planets.id", ondelete="CASCADE"), nullable=False, index=True)
    space_id = Column(String(100), nullable=True, index=True) # Optional scoping to a space
    
    category = Column(String(50), nullable=False, index=True) # now, smart, explore
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False) # The core insight/description
    impact = Column(Text, nullable=True) # Analysis of what this means for the business
    reason = Column(String(100), nullable=True) # Badge text like "Critical Risk"
    
    icon = Column(String(100), nullable=True) # Lucide icon name
    color = Column(String(50), nullable=True) # red, orange, blue, purple
    
    cta_label = Column(String(255), nullable=True) # Text on the action button
    cta_action = Column(String(100), nullable=True) # Type of action (e.g., 'open_chat')
    cta_params = Column(JSON, nullable=True) # Parameters for the action (e.g., initial query)
    
    chart_data = Column(JSON, nullable=True) # Data for the preview chart
    
    confidence = Column(Float, nullable=True, default=1.0)
    
    is_dismissed = Column(DateTime, nullable=True) # Timestamp when the user dismissed the signal
    
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
    planet = relationship("Planet")

    def __repr__(self):
        return f"<IntelligenceSignal(id={self.id}, title={self.title}, category={self.category})>"
