"""Service principal model — non-human identity for agents.

One SP per crew OR one SP per space (exactly one of crew_id / space_id is set).
Agents owned by a collaborative scope run as this identity so that data access
survives the creator leaving the crew/space.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite test fallback — see src/models/audit.py for the rationale.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class ServicePrincipal(Base):
    """One service principal per crew OR per space. Agents run as this identity."""

    __tablename__ = "service_principals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    name = Column(String(255), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    permissions_snapshot = Column(_JSONB_OR_JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        # CURRENT_TIMESTAMP is SQL standard; works on both PostgreSQL and SQLite.
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "(crew_id IS NOT NULL) <> (space_id IS NOT NULL)",
            name="ck_service_principals_owner_exactly_one",
        ),
    )

    def __repr__(self) -> str:
        owner = f"crew={self.crew_id}" if self.crew_id else f"space={self.space_id}"
        return f"<ServicePrincipal(id={self.id}, {owner}, name={self.name})>"
