"""Planet models."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Planet(Base):
    """Planet model."""

    __tablename__ = "planets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # personal, team
    color = Column(String(7), nullable=False)  # Hex color
    icon = Column(String(255), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=False, server_default="false")
    last_accessed = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_planets")
    members = relationship("PlanetMember", back_populates="planet", cascade="all, delete-orphan")
    dashboards = relationship("Dashboard", back_populates="planet", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_planets_owner_id", "owner_id", postgresql_where=deleted_at.is_(None)),
        Index("idx_planets_type", "type", postgresql_where=deleted_at.is_(None)),
        Index("idx_planets_is_active", "is_active", postgresql_where=deleted_at.is_(None)),
        Index("idx_planets_last_accessed", "last_accessed"),
    )

    def __repr__(self) -> str:
        return f"<Planet(id={self.id}, name={self.name}, type={self.type})>"


class PlanetMember(Base):
    """Planet member model."""

    __tablename__ = "planet_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    planet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(
        String(50), nullable=False
    )  # owner, admin, member, viewer
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    # Relationships
    planet = relationship("Planet", back_populates="members")
    user = relationship("User", back_populates="planet_memberships")

    __table_args__ = (
        Index(
            "idx_planet_members_planet_user",
            "planet_id",
            "user_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<PlanetMember(planet_id={self.planet_id}, user_id={self.user_id}, role={self.role})>"

