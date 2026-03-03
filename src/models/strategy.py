"""Strategy models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from src.config.database import Base


class StrategicPillar(Base):
    """Strategic Pillar model."""

    __tablename__ = "strategic_pillars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(50), nullable=True)

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    objectives = relationship("StrategicObjective", back_populates="pillar", cascade="all, delete-orphan")


class StrategicObjective(Base):
    """Strategic Objective model."""

    __tablename__ = "strategic_objectives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pillar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategic_pillars.id", ondelete="SET NULL"),
        nullable=True,
    )
    type = Column(String(50), nullable=False)  # corporate, unit, team
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    horizon = Column(String(50), nullable=True)
    area = Column(String(100), nullable=True)
    priority = Column(String(50), nullable=True)
    weight = Column(Float, nullable=True, default=1.0)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    pillar = relationship("StrategicPillar", back_populates="objectives")
    okrs = relationship("StrategyOKR", back_populates="objective", cascade="all, delete-orphan")
    assumptions = relationship("StrategyAssumption", back_populates="objective")


class StrategyOKR(Base):
    """Strategy OKR model."""

    __tablename__ = "strategy_okrs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    objective_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategic_objectives.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    linked_kpi_id = Column(String(100), nullable=True)  # Reference to external metrics system
    baseline = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    measurement_frequency = Column(String(50), nullable=True)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    objective = relationship("StrategicObjective", back_populates="okrs")
    key_results = relationship("StrategyKeyResult", back_populates="okr", cascade="all, delete-orphan")


class StrategyKeyResult(Base):
    """Strategy Key Result model."""

    __tablename__ = "strategy_key_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    okr_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategy_okrs.id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(Text, nullable=False)
    baseline = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True, default=0.0)
    unit = Column(String(50), nullable=True)

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    okr = relationship("StrategyOKR", back_populates="key_results")


class StrategyInitiative(Base):
    """Strategy Initiative model."""

    __tablename__ = "strategy_initiatives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )
    budget_estimated = Column(Float, nullable=True)
    expected_impact = Column(Text, nullable=True)
    status = Column(String(50), nullable=True, default="planned")
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    alignment_score = Column(Integer, nullable=True, default=0)
    supports_objectives = Column(JSON, nullable=True, default=list)  # List of UUIDs

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )


class StrategyAssumption(Base):
    """Strategy Assumption model."""

    __tablename__ = "strategy_assumptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    confidence = Column(String(50), nullable=True)  # Low, Medium, High
    validated = Column(Boolean, nullable=False, default=False)
    revision_deadline = Column(DateTime(timezone=True), nullable=True)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_objective_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategic_objectives.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Audit info
    created_at = Column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    # Relationships
    objective = relationship("StrategicObjective", back_populates="assumptions")
