"""Enterprise API models."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class EnterpriseAPI(Base):
    """Enterprise API registry model."""

    __tablename__ = "enterprise_apis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    base_url = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Store endpoints and their schemas as JSON
    # endpoints: list of {path: string, method: string, description: string, fields: list of {name: string, type: string}}
    endpoints = Column(JSON, nullable=True, default=[])

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
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

    def __repr__(self) -> str:
        return f"<EnterpriseAPI(id={self.id}, name={self.name})>"
