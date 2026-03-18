"""Crew models."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Crew(Base):
    """Crew model."""

    __tablename__ = "crews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    space = relationship("Space", back_populates="crews")
    members = relationship("CrewMember", back_populates="crew", cascade="all, delete-orphan")
    crew_connections = relationship(
        "CrewConnection", back_populates="crew", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_crews_space_id", "space_id", postgresql_where=deleted_at.is_(None)),
        Index("idx_crews_created_by", "created_by", postgresql_where=deleted_at.is_(None)),
    )

    def __repr__(self) -> str:
        return f"<Crew(id={self.id}, name={self.name}, space_id={self.space_id})>"


class CrewMember(Base):
    """Crew member model."""

    __tablename__ = "crew_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(50), nullable=False)  # commander, navigator, explorer, guest
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    crew = relationship("Crew", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("crew_id", "user_id", name="uq_crew_members_crew_user"),
        Index("idx_crew_members_crew_id", "crew_id"),
        Index("idx_crew_members_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<CrewMember(crew_id={self.crew_id}, user_id={self.user_id}, role={self.role})>"


class CrewConnection(Base):
    """Crew-Connection association table."""

    __tablename__ = "crew_connections"

    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # Relationships
    crew = relationship("Crew", back_populates="crew_connections")
    connection = relationship("DataConnection")

    __table_args__ = (
        Index("idx_crew_connections_crew_id", "crew_id"),
        Index("idx_crew_connections_connection_id", "connection_id"),
    )

    def __repr__(self) -> str:
        return f"<CrewConnection(crew_id={self.crew_id}, connection_id={self.connection_id})>"
