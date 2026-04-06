import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class AgentScope(str, Enum):
    PERSONAL = "personal"
    SPACE = "space"
    CREW = "crew"
    ORGANIZATION = "organization"


class AgentStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    CONFIGURING = "configuring"


class AgentFrequency(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class AgentArchetype(str, Enum):
    FINANCIAL_ANALYST = "financial_analyst"
    OPERATIONS_MONITOR = "operations_monitor"
    STRATEGY_TRACKER = "strategy_tracker"
    GROWTH_INTELLIGENCE = "growth_intelligence"
    RISK_RADAR = "risk_radar"
    CUSTOM = "custom"


class FindingType(str, Enum):
    INSIGHT = "insight"
    OPPORTUNITY = "opportunity"
    RISK = "risk"


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Agent(Base):
    """Autonomous AI agent that monitors data connections on a schedule."""

    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    archetype = Column(String(50), nullable=False, default="custom")
    scope = Column(String(20), nullable=False, index=True)  # personal, space, crew, organization
    scope_id = Column(String(255), nullable=False, index=True)  # ID of the scope entity
    scope_name = Column(String(255), nullable=True)

    status = Column(String(20), nullable=False, default="configuring", index=True)
    monitor_type = Column(String(20), nullable=False, default="question")  # question, datasource, sql
    focus = Column(Text, nullable=True)  # The question or instructions for the agent
    custom_sql = Column(Text, nullable=True)  # For sql monitor_type
    frequency = Column(String(20), nullable=False, default="daily")
    depth = Column(String(20), nullable=True, default="standard")  # quick, standard, deep

    # Data sources this agent monitors
    connection_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=[])
    table_ids = Column(ARRAY(String), nullable=True)  # Granular table selection

    # Previous execution answer for comparison
    last_answer = Column(Text, nullable=True)

    # Organization scope: spaces to traverse + relationship types
    space_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=True)
    relationship_types = Column(ARRAY(String), nullable=True)

    # Execution tracking
    last_execution_at = Column(DateTime(timezone=True), nullable=True)
    next_execution_at = Column(DateTime(timezone=True), nullable=True)
    executions_this_month = Column(Integer, nullable=False, default=0)
    cycles_consumed = Column(Integer, nullable=False, default=0)

    # Ownership
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )

    # Relationships
    findings = relationship("AgentFinding", back_populates="agent", cascade="all, delete-orphan", order_by="AgentFinding.created_at.desc()")
    executions = relationship("AgentExecution", back_populates="agent", cascade="all, delete-orphan", order_by="AgentExecution.started_at.desc()")
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, scope={self.scope}, status={self.status})>"


class AgentFinding(Base):
    """A finding produced by an agent execution — an insight, opportunity, or risk."""

    __tablename__ = "agent_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    type = Column(String(20), nullable=False, index=True)  # insight, opportunity, risk
    severity = Column(String(20), nullable=False, default="medium")
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)  # 0.0 - 1.0

    # Detailed analysis
    query = Column(Text, nullable=True)  # What the agent was looking for
    evidence = Column(Text, nullable=True)  # Raw data/evidence
    reasoning = Column(Text, nullable=True)  # Step-by-step reasoning
    recommendation = Column(Text, nullable=True)  # Recommended action
    data_sources = Column(ARRAY(String), nullable=True)  # tables/columns analyzed

    # Context
    connection_id = Column(UUID(as_uuid=True), nullable=True)
    connection_name = Column(String(255), nullable=True)

    # State
    dismissed = Column(Boolean, nullable=False, default=False)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    added_to_page_id = Column(UUID(as_uuid=True), nullable=True)  # If user added to a dashboard

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    agent = relationship("Agent", back_populates="findings")
    execution = relationship("AgentExecution", back_populates="findings")

    def __repr__(self):
        return f"<AgentFinding(id={self.id}, type={self.type}, title={self.title[:50]})>"


class AgentExecution(Base):
    """Record of a single agent execution (one 'beat')."""

    __tablename__ = "agent_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    cycles_consumed = Column(Integer, nullable=False, default=0)
    findings_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)  # The AI's answer for comparison
    sql_executed = Column(Text, nullable=True)  # The SQL that was run

    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="executions")
    findings = relationship("AgentFinding", back_populates="execution")

    def __repr__(self):
        return f"<AgentExecution(id={self.id}, agent_id={self.agent_id}, status={self.status})>"
