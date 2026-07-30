import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from src.config.database import Base


# SQLite has no native ARRAY type, so the test suite (which uses
# sqlite+aiosqlite in memory) fails to create these tables with CompileError.
# Give every ARRAY column a variant that falls back to JSON on SQLite — the
# production dialect (PostgreSQL) still uses the native ARRAY type, so this
# is a zero-migration change.
def _array_with_sqlite_variant(inner_type):
    return ARRAY(inner_type).with_variant(JSON(), "sqlite")


# Same story for JSONB — fall back to plain JSON on SQLite.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


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
    # `schedule_jsonb` is the precise source of truth for cadence
    # (interval_value + interval_unit + end condition). These enum
    # values are coarse buckets kept for backward compatibility with
    # existing rows and the legacy UI select; new flexible schedules
    # pass `manual` here and rely on `schedule_jsonb`.
    MINUTELY = "minutely"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MANUAL = "manual"
    ONCE = "once"


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
    monitor_type = Column(
        String(20), nullable=False, default="question"
    )  # question, datasource, sql
    focus = Column(Text, nullable=True)  # The question or instructions for the agent
    custom_sql = Column(Text, nullable=True)  # For sql monitor_type
    frequency = Column(String(20), nullable=False, default="daily")
    depth = Column(String(20), nullable=True, default="standard")  # quick, standard, deep

    # Data sources this agent monitors
    connection_ids = Column(
        _array_with_sqlite_variant(UUID(as_uuid=True)), nullable=False, default=[]
    )
    table_ids = Column(
        _array_with_sqlite_variant(String), nullable=True
    )  # Granular table selection

    # Selected context — everything in Universe Intelligence that can be
    # scoped to an agent, indexed by entity kind. Keys mirror what the
    # DataSourcePicker surfaces. After the Knowledge refactor (Phase 1)
    # the supported kinds shrink to: Knowledge (glossary_terms — and in
    # Phase 2, metrics), Relationships (enterprise_relationships), and
    # Outputs (widgets, insights, pages).
    # Empty arrays or missing keys mean "no filter — include everything
    # the RAG can see in scope".
    # Example:
    #   {
    #     "glossary_terms": ["uuid-9"],
    #     "enterprise_relationships": [],
    #     "widgets": [],
    #   }
    selected_context = Column(_JSONB_OR_JSON, nullable=True)

    # Previous execution answer for comparison
    last_answer = Column(Text, nullable=True)

    # Transcript of the AI chat conversation this agent was created from.
    # Populated only when the "Create agent from this chat" CTA is used
    # (frontend passes the last N messages as a readable transcript).
    # Otherwise NULL — legacy agents and sidebar-originated creations
    # don't carry chat context.
    chat_context = Column(Text, nullable=True)

    # Organization scope: spaces to traverse + relationship types
    space_ids = Column(_array_with_sqlite_variant(UUID(as_uuid=True)), nullable=True)
    relationship_types = Column(_array_with_sqlite_variant(String), nullable=True)

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

    # --- Identity (user vs service principal) ---
    # identity_type='user' → agent runs under `created_by`
    # identity_type='service_principal' → agent runs under `service_principal_id`
    identity_type = Column(
        String(20),
        nullable=False,
        server_default="user",
    )
    service_principal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_principals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Insight mode linkage ---
    widget_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=True,
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Flexible schedule (replaces the coarse `frequency` enum over time) ---
    # Shape: { "interval_value": int, "interval_unit": "minute"|"hour"|"day"|"week", "timezone": str? }
    schedule_jsonb = Column(_JSONB_OR_JSON, nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)

    # --- Delta strategy ---
    delta_strategy = Column(
        String(10),
        nullable=False,
        server_default="hash",
    )

    # --- Behaviour ---
    notify_on_change = Column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    # Phase 6 — when true the agent runtime drops every connection whose
    # tier ≠ 'internal' before issuing the query. Used by compliance-
    # bound deploys that only want autonomous agents touching low-risk
    # data sources.
    auditable_only = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    consecutive_failures = Column(
        Integer,
        nullable=False,
        server_default="0",
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
    # No delete cascade: deleting an agent detaches its findings/executions
    # (FK ON DELETE SET NULL) instead of erasing them — see the agent_id
    # columns below. passive_deletes lets the DB perform the SET NULL without
    # the ORM loading and rewriting every child row first.
    findings = relationship(
        "AgentFinding",
        back_populates="agent",
        passive_deletes=True,
        order_by="AgentFinding.created_at.desc()",
    )
    executions = relationship(
        "AgentExecution",
        back_populates="agent",
        passive_deletes=True,
        order_by="AgentExecution.started_at.desc()",
    )
    creator = relationship("User", foreign_keys=[created_by])
    service_principal = relationship("ServicePrincipal", foreign_keys=[service_principal_id])

    __table_args__ = (
        CheckConstraint(
            "identity_type IN ('user', 'service_principal')",
            name="ck_agents_identity_type_valid",
        ),
        CheckConstraint(
            "delta_strategy IN ('hash', 'llm')",
            name="ck_agents_delta_strategy_valid",
        ),
        Index(
            "idx_agents_widget_id",
            "widget_id",
            postgresql_where=text("widget_id IS NOT NULL"),
        ),
        Index(
            "idx_agents_ends_at",
            "ends_at",
            postgresql_where=text("ends_at IS NOT NULL"),
        ),
    )

    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, scope={self.scope}, status={self.status})>"


class AgentFinding(Base):
    """A finding produced by an agent execution — an insight, opportunity, or risk."""

    __tablename__ = "agent_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SET NULL (not CASCADE): deleting an agent must NOT erase the insights it
    # already produced. The finding is kept and simply detached from the agent
    # (agent_id -> NULL). Insights added to a page are independent widgets that
    # survive anyway; this preserves the finding history too.
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
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
    data_sources = Column(
        _array_with_sqlite_variant(String), nullable=True
    )  # tables/columns analyzed
    # Structured tabular result set produced by the agent's SQL/datasource
    # run. Shape: {"columns": ["col1", "col2"], "data": [[...], [...]],
    # "truncated": bool?}. Null when the agent ran in question-only mode
    # or produced no tabular output. Consumed by the frontend Insight
    # Cockpit chart picker.
    rows = Column(_JSONB_OR_JSON, nullable=True)

    # Sprint 1.17 round 5 — viz_kind tells the Pulse FE which card
    # variant + recharts widget kind to render. When NULL the FE
    # falls back to a deterministic hash on the finding id, which
    # keeps legacy findings rendering, but new agents should always
    # tag themselves so the user sees a consistent "agent → widget"
    # contract end-to-end. Allowed kinds mirror the toolbar chart
    # picker registry: bar, line, donut, pie, kpi, big_number,
    # delta, range, heatmap, sparkline, text, list.
    viz_kind = Column(String(40), nullable=True)

    # ── BE-03 (Sky Mobile) — structured feed fields ──────────────────
    # The mobile Insights surface renders machine-readable objects, not
    # prose. ``series`` is the sparkline/area series behind the headline
    # number ([{"t": ..., "v": ...}], may be [] for aggregate-only
    # findings). ``stat_tiles`` are the up-to-3 key/value pairs shown on
    # the detail ([{"label": ..., "value": ...}]).
    series = Column(_JSONB_OR_JSON, nullable=True)
    stat_tiles = Column(_JSONB_OR_JSON, nullable=True)
    # ``source`` distinguishes an autonomous *scan* finding from a
    # registered-*agent* finding. Scan findings have no ``agent_id`` (the
    # scan agent is not a persisted Agent row), so they carry their own
    # ``space_id`` + ``agent_name`` for scoping and display.
    source = Column(
        String(20),
        nullable=False,
        default="agent",
        server_default=text("'agent'"),
    )
    space_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    agent_name = Column(String(255), nullable=True)

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
    # SET NULL (not CASCADE): keep the execution history when the agent is
    # deleted, so the findings it produced (which reference this execution)
    # retain their context instead of being erased.
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    cycles_consumed = Column(Integer, nullable=False, default=0)
    findings_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)  # The AI's answer for comparison
    sql_executed = Column(Text, nullable=True)  # The SQL that was run

    # --- Delta detection ---
    result_hash = Column(String(64), nullable=True)
    result_payload = Column(_JSONB_OR_JSON, nullable=True)
    delta_kind = Column(String(20), nullable=True)  # 'first_run' | 'none' | 'trivial' | 'material'
    delta_summary = Column(Text, nullable=True)
    delta_tokens = Column(Integer, nullable=True)
    delta_cost_usd = Column(Numeric(10, 4), nullable=True)

    # --- Main-execution cost ---
    llm_tokens_used = Column(Integer, nullable=True)
    llm_cost_usd = Column(Numeric(10, 4), nullable=True)

    # Insights-Analytics tier classifier — see src/services/insights_tier.py.
    # 'l1' = trivial / no findings, 'l2' = triage, 'l3' = deep dive.
    # NULL on legacy rows; aggregator falls back to 'l1'.
    tier = Column(String(2), nullable=True)

    # --- Identity audit ---
    triggered_by_sp_id = Column(
        UUID(as_uuid=True),
        ForeignKey("service_principals.id", ondelete="SET NULL"),
        nullable=True,
    )
    attributed_to_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notification_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    duration_ms = Column(Integer, nullable=True)

    # --- Context-layer evidence trail (Phase 2.6) ---
    # Which context_documents this run retrieved, and which intent the
    # supervisor classified the prompt as. Kept as an array of UUIDs
    # rather than a FK relationship because we never hard-delete
    # context_documents, and the list may reference soft-deleted rows.
    context_doc_ids = Column(
        _array_with_sqlite_variant(UUID(as_uuid=True)),
        nullable=False,
        default=list,
    )
    context_intent = Column(String(32), nullable=True)

    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="executions")
    findings = relationship("AgentFinding", back_populates="execution")

    __table_args__ = (
        CheckConstraint(
            "delta_kind IS NULL OR delta_kind IN ('first_run', 'none', 'trivial', 'material')",
            name="ck_agent_executions_delta_kind_valid",
        ),
        Index("idx_agent_executions_agent_started", "agent_id", "started_at"),
        Index(
            "idx_agent_executions_delta_kind",
            "delta_kind",
            postgresql_where=text("delta_kind = 'material'"),
        ),
    )

    def __repr__(self):
        return f"<AgentExecution(id={self.id}, agent_id={self.agent_id}, status={self.status})>"
