"""Service principal model — non-human identity for agents within a crew."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.config.database import Base


class ServicePrincipal(Base):
    """One service principal per crew. Agents run as this identity."""

    __tablename__ = "service_principals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name = Column(String(255), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    permissions_snapshot = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<ServicePrincipal(id={self.id}, crew_id={self.crew_id}, name={self.name})>"
