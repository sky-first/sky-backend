"""Strategy models."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, func
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
    horizon = Column(String(50), nullable=True)
    owner = Column(String(100), nullable=True)
    metrics = Column(JSON, nullable=True, default=list)
    priority = Column(String(50), nullable=True)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True)

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    objectives = relationship(
        "StrategicObjective", back_populates="pillar", cascade="all, delete-orphan"
    )


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
    status = Column(String(50), nullable=True, default="on_track")
    priority = Column(String(50), nullable=True)
    area = Column(String(100), nullable=True)
    owner = Column(String(100), nullable=True)
    kpis = Column(JSON, nullable=True, default=list)
    budget = Column(Float, nullable=True)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True)

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    pillar = relationship("StrategicPillar", back_populates="objectives")
    okrs = relationship("StrategyOKR", back_populates="objective", cascade="all, delete-orphan")
    assumptions = relationship(
        "StrategyAssumption", back_populates="objective", cascade="all, delete-orphan"
    )


class StrategyCycle(Base):
    """Strategy Cycle model (Quarterly, Annual, etc)."""

    __tablename__ = "strategy_cycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # quarterly, annual, monthly
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(50), nullable=True, default="active")

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    okrs = relationship("StrategyOKR", back_populates="cycle")


class StrategyOKR(Base):
    """Strategy OKR model."""

    __tablename__ = "strategy_okrs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    objective_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategic_objectives.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategy_cycles.id", ondelete="SET NULL"),
        nullable=True,
    )

    title = Column(String(255), nullable=False)
    linked_kpi_id = Column(
        String(100), nullable=True
    )  # Reference to external metrics system
    baseline = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    measurement_frequency = Column(String(50), nullable=True)
    owner_crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
    )
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True)

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    objective = relationship("StrategicObjective", back_populates="okrs")
    cycle = relationship("StrategyCycle", back_populates="okrs")
    key_results = relationship(
        "StrategyKeyResult", back_populates="okr", cascade="all, delete-orphan"
    )


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
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
    type = Column(String(50), nullable=True)
    pillar_id = Column(UUID(as_uuid=True), nullable=True)
    objective_id = Column(UUID(as_uuid=True), nullable=True)
    unit = Column(String(100), nullable=True)
    owner = Column(String(100), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=True, default="planned")
    impact = Column(Text, nullable=True)
    budget = Column(Float, nullable=True)
    risks = Column(JSON, nullable=True, default=list)
    assumptions = Column(JSON, nullable=True, default=list)
    progress = Column(Integer, nullable=True, default=0)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True)

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )


class StrategyAssumption(Base):
    """Strategy Assumption model."""

    __tablename__ = "strategy_assumptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    linked_objective_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategic_objectives.id", ondelete="SET NULL"),
        nullable=True,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    impact_score = Column(Integer, nullable=True, default=3)
    probability_score = Column(Integer, nullable=True, default=3)
    priority = Column(String(50), nullable=True)
    impacted_entities = Column(JSON, nullable=True, default=list)
    source = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True, default="identified")
    mitigation_plan = Column(Text, nullable=True)
    owner = Column(String(100), nullable=True)
    space_id = Column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True)
    crew_id = Column(UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=True, index=True)

    # Audit info
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    objective = relationship("StrategicObjective", back_populates="assumptions")
