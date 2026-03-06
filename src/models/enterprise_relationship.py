"""Enterprise Relationship models."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from src.config.database import Base


class EnterpriseRelationship(Base):
    """Enterprise Relationship model."""

    __tablename__ = "user_enterprise_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # sources: list of {id: string, type: string}
    sources = Column(JSON, nullable=False)

    target_id = Column(String(255), nullable=False)
    target_type = Column(String(50), nullable=False)  # connection, dataset, table
    target_details = Column(JSON, nullable=True)

    relationship_type = Column(String(50), nullable=False)  # maps_to, derived_from, etc.

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return f"<EnterpriseRelationship(id={self.id}, name={self.name})>"
