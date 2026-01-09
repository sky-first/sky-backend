"""Template model."""

import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class Template(Base):
    """Template model."""

    __tablename__ = "templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    creator = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    thumbnail = Column(Text, nullable=True)
    question = Column(Text, nullable=True)
    widgets = Column(
        JSON, nullable=False, default=list, server_default="[]"
    )  # Array of widget definitions
    icon = Column(String(255), nullable=True)
    color = Column(String(7), nullable=False)  # Hex color
    popular = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    enterprise = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("idx_templates_category", "category"),
        Index("idx_templates_popular", "popular"),
        Index("idx_templates_enterprise", "enterprise"),
    )

    def __repr__(self) -> str:
        return f"<Template(id={self.id}, name={self.name}, category={self.category})>"
