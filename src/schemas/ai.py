"""AI schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.ai_transparency import AIResponseTransparency  # W7


class ConfigureData(BaseModel):
    """AI configuration data schema."""

    question: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    response_format: Optional[str] = None
    creativity: int = Field(default=50, ge=0, le=100)
    length: int = Field(default=50, ge=0, le=100)
    knowledge: List[str] = Field(default_factory=list)  # Connection IDs or table names
    sql_instructions: Optional[str] = None
    # Knowledge layer markdown — Metrics + Glossary visible to the user,
    # Org-certified rows first. Populated by ai_service.process_query
    # via knowledge_context_loader and spliced into the engine prompt.
    knowledge_context: Optional[str] = None


class AIQueryRequest(BaseModel):
    """AI query request schema."""

    question: str = Field(..., min_length=1)
    widget_id: Optional[UUID] = None
    knowledge: Optional[List[str]] = None
    configure_data: Optional[ConfigureData] = None
    space_id: Optional[str] = Field(None, description="Space ID for the query context")
    is_personal: Optional[bool] = Field(
        default=False,
        description="Whether the query is in personal mode (access across all crews/spaces).",
    )
    page_id: Optional[UUID] = Field(None, description="Page ID for tenant isolation")
    # Conversation identity for multi-turn memory (Frente 1). The frontend sends a
    # STABLE id per chat surface — the active chat-session id for the main chatbox
    # (page-scoped, so a shared page's default "Chat 1" is the same id for every
    # member → shared memory), or the conversation id for a reply/thread. The AI
    # keys chat_history on this; a stable value across turns is what loads memory.
    # Absent → process_query falls back to the per-query AIQuery id (no memory).
    thread_id: Optional[str] = Field(
        None,
        description=(
            "Stable conversation/session id for multi-turn memory. Same across "
            "turns of the same chat tab/thread. Omit for one-shot queries."
        ),
    )
    # Collaborative mode: restrict AI data context to this specific crew
    crew_id: Optional[str] = Field(
        None,
        description=(
            "Active crew ID. When set, the AI will only use data accessible to this crew "
            "(collaborative mode). When None + is_personal=False, uses all crews the user "
            "belongs to in the space."
        ),
    )
    # Knowledge Library: file IDs the user explicitly @mentioned in the prompt.
    # The AI service boosts their chunks 10× during RAG retrieval.
    mentioned_file_ids: Optional[List[str]] = Field(
        default=None,
        description="Knowledge file IDs @mentioned by the user. Boosted during RAG retrieval.",
    )
    # User's preferred locale — injected into the LLM system prompt so the AI
    # responds in the selected language. Defaults to "pt" when absent.
    locale: Optional[str] = Field(
        default=None,
        description="User's preferred locale ('pt' | 'en'). Injected into LLM system prompt.",
    )

    @field_validator("locale", mode="before")
    @classmethod
    def _normalize_locale(cls, v: object) -> object:
        if v is None:
            return None
        from src.core.locale import normalize_locale
        return normalize_locale(str(v))


class AIQueryResponse(BaseModel):
    """AI query response schema."""

    id: UUID
    question: str
    answer: Optional[str] = None
    data_sample: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Sample data from query execution (max 15 rows)"
    )
    sql: Optional[str] = Field(default=None, description="Generated SQL query")
    status: str  # processing, completed, error
    pipeline_id: Optional[UUID] = None
    chosen_table: Optional[str] = Field(
        default=None, description="Table chosen by AI to answer the question"
    )
    chosen_datasets: Optional[List[str]] = Field(
        default=None, description="Datasets chosen by AI to answer the question"
    )
    # NEW: extra meta returned by the AI execution engine (e.g., dynamic widget title)
    meta: Optional[Dict[str, Any]] = None
    page_id: UUID
    created_at: datetime
    updated_at: datetime

    # W7 — optional transparency bundle (evidence + reasoning + flags).
    transparency: Optional["AIResponseTransparency"] = None

    model_config = ConfigDict(from_attributes=True)


class SuggestWidgetTitleRequest(BaseModel):
    """Request to suggest a better title for a single widget created from an AI answer."""

    question: str = Field(..., min_length=1, max_length=4000)
    data_sample: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Sample data for the widget (max 15 rows)"
    )
    answer: Optional[str] = Field(default=None, description="Optional AI textual answer")
    current_title: Optional[str] = Field(
        default=None, description="Current (fallback) title shown in the UI"
    )
    language: str = Field(default="pt", min_length=2, max_length=8)
    space_id: Optional[str] = Field(
        default=None, description="Space ID used for permissions/catalog context"
    )
    is_personal: Optional[bool] = Field(
        default=False,
        description="Whether the action is in personal mode (access across all crews/spaces).",
    )
    crew_id: Optional[str] = Field(
        None,
        description="Active crew ID for collaborative context.",
    )


class SuggestWidgetTitleResponse(BaseModel):
    """Suggested widget title response."""

    title: str


class ChatMessageRequest(BaseModel):
    """Chat message request schema."""

    message: str = Field(..., min_length=1)
    widget_id: UUID
    page_id: Optional[UUID] = Field(None, description="Page ID for tenant isolation")
    context: Optional[Dict[str, Any]] = None
    # Explicit collaborative context fields (preferred over context dict)
    space_id: Optional[str] = Field(None, description="Space ID for context")
    crew_id: Optional[str] = Field(None, description="Active crew ID (collaborative mode)")
    is_personal: Optional[bool] = Field(default=False, description="Personal mode flag")
    # AI Customization (Settings → AI Customization tab).
    # When absent, the route handler falls back to current_user.preferences.
    ai_tone: Optional[str] = Field(
        None,
        description="Preferred response tone (casual, professional, technical, friendly).",
    )
    ai_style: Optional[str] = Field(
        None,
        description="Preferred output structure (concise, detailed, step-by-step).",
    )
    # User's preferred locale — injected into the LLM system prompt so the AI
    # responds only in the selected language. Auto-injected by the frontend.
    locale: Optional[str] = Field(
        default=None,
        description="User's preferred locale ('pt' | 'en'). Injected into LLM system prompt.",
    )

    @field_validator("locale", mode="before")
    @classmethod
    def _normalize_locale(cls, v: object) -> object:
        if v is None:
            return None
        from src.core.locale import normalize_locale
        return normalize_locale(str(v))


class ChatMessageResponse(BaseModel):
    """Chat message response schema."""

    id: UUID
    type: str  # user, assistant
    content: str
    page_id: UUID
    timestamp: datetime

    # W7 — optional transparency bundle. Omitted from serialization
    # when absent (old clients see no new field). Populated for
    # assistant responses only.
    transparency: Optional["AIResponseTransparency"] = None

    model_config = ConfigDict(from_attributes=True)


class AIHistoryItem(BaseModel):
    """AI history item schema."""

    id: UUID
    query: str
    preview: str
    answer: str
    date: datetime
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    pinned: bool = False
    page_id: UUID
    created_at: datetime
    updated_at: datetime
    # Collaborative context filters
    space_id: Optional[str] = None
    crew_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CreateHistoryRequest(BaseModel):
    """Create history request schema."""

    query: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    page_id: Optional[UUID] = Field(None, description="Page ID for tenant isolation")
    category: Optional[str] = None
    tags: Optional[List[str]] = Field(default_factory=list)
    # Collaborative context
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    # Real end-to-end query latency in milliseconds — feeds Settings → Usage.
    duration_ms: Optional[int] = Field(
        None, description="Query latency in ms (client-measured or server-measured)"
    )


class FeedbackRequest(BaseModel):
    """Feedback request schema."""

    # Preferido: associar feedback ao AIQuery (ai_queries.id)
    query_id: Optional[UUID] = Field(
        default=None,
        description="AI query ID (ai_queries.id) to associate this feedback with.",
    )
    # Deprecado (mantido por compatibilidade com clientes antigos)
    message_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Deprecated. Prefer 'query_id'.",
    )
    feedback: str = Field(..., pattern="^(good|bad)$")
    comment: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional comment explaining what was wrong (typically used with feedback='bad').",
    )


class GenerateSQLRequest(BaseModel):
    """Generate SQL request schema."""

    question: str = Field(..., min_length=1)
    knowledge: List[str] = Field(..., min_length=1)  # Table names or connection IDs
    sql_instructions: Optional[str] = None
    creativity: int = Field(default=50, ge=0, le=100)
    locale: Optional[str] = Field(
        default=None,
        description="User's preferred locale ('pt' | 'en'). Injected into LLM system prompt.",
    )

    @field_validator("locale", mode="before")
    @classmethod
    def _normalize_locale(cls, v: object) -> object:
        if v is None:
            return None
        from src.core.locale import normalize_locale
        return normalize_locale(str(v))


class GenerateSQLResponse(BaseModel):
    """Generate SQL response schema."""

    sql: str
    explanation: Optional[str] = None


class PipelineStepResponse(BaseModel):
    """Pipeline step response schema."""

    id: str
    name: str
    kind: str  # question, orchestrator, project, sql, tables, answer
    status: str  # COMPLETED, PROCESSING, PENDING, ERROR
    content: str
    logs: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PipelineResponse(BaseModel):
    """Pipeline response schema."""

    id: UUID
    query_id: UUID
    status: str  # processing, completed, error
    steps: List[PipelineStepResponse]
    current_step: Optional[str] = None
    errors: Optional[List[Dict[str, Any]]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineExecuteRequest(BaseModel):
    """Pipeline execute request schema."""

    question: str = Field(..., min_length=1)
    knowledge: List[str] = Field(default_factory=list)
    configure_data: ConfigureData
    page_id: Optional[UUID] = Field(None, description="Page ID for tenant isolation")


class PipelineExecuteResponse(BaseModel):
    """Pipeline execute response schema."""

    pipeline_id: UUID
    status: str  # processing, completed, error


class GenerateAnswerRequest(BaseModel):
    """Generate answer request schema."""

    question: str = Field(..., min_length=1)
    knowledge: List[str] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


class GenerateAnswerResponse(BaseModel):
    """Generate answer response schema."""

    answer: str
    timestamp: datetime


class AnalyzeQuestionRequest(BaseModel):
    """Analyze question request schema."""

    question: str = Field(..., min_length=1)
    knowledge: List[str] = Field(default_factory=list)


class AnalyzeQuestionResponse(BaseModel):
    """Analyze question response schema."""

    intent: str
    entities: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class ChatBootstrapSuggestion(BaseModel):
    """Suggestion card shown when opening a new chat.

    A suggestion can be either:
    - a normal question card (kind='question'), which sends `question` to chat
    - an action card (kind='action'), which triggers an in-app action (e.g. create dashboard)
    """

    title: str
    kind: str = Field(default="question", pattern="^(question|action)$")
    question: Optional[str] = None
    action_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class ChatBootstrapResponse(BaseModel):
    """Greeting + suggestions for a new chat session."""

    greeting: str
    suggestions: List[ChatBootstrapSuggestion]
    meta: Optional[Dict[str, Any]] = None


class ValidateSQLRequest(BaseModel):
    """Request para validar SQL."""

    connection_id: str = Field(..., description="ID da conexão.")
    sql: str = Field(..., description="SQL a ser validado.")
    user_id: Optional[str] = Field(None, description="ID do usuário.")
    space_id: Optional[str] = Field(None, description="Space atual.")
    crew_ids: Optional[List[str]] = Field(None, description="Crew IDs.")
    is_personal: Optional[bool] = Field(False, description="Modo personal.")
    include_explanation: Optional[bool] = Field(
        default=False,
        description="If True, asks the AI engine to generate a short explanation of the preview results.",
    )
    question: Optional[str] = Field(
        default=None,
        description="Original user question (context for explanation).",
    )


class ValidateSQLResponse(BaseModel):
    """Response da validação de SQL."""

    is_valid: bool = Field(..., description="Se o SQL é válido.")
    error: Optional[str] = Field(None, description="Mensagem de erro.")
    preview_data: Optional[List[Dict[str, Any]]] = Field(None, description="Preview dos dados.")
    num_rows: Optional[int] = Field(None, description="Número de linhas.")
    execution_time_ms: Optional[float] = Field(None, description="Tempo de execução.")
    columns: Optional[List[str]] = Field(None, description="Colunas retornadas.")
    explanation: Optional[str] = Field(
        default=None,
        description="Short AI-generated explanation for the preview results (if requested).",
    )


class InfographicDataDriver(BaseModel):
    """Driver item for infographic."""

    name: str
    icon: Optional[str] = None
    impact: Optional[str] = None
    description: Optional[str] = None


class InfographicData(BaseModel):
    """Structured data for infographic widget."""

    # Header
    title: Optional[str] = None
    subtitle: Optional[str] = None
    mainValue: Optional[str] = None
    mainValueLabel: Optional[str] = None

    # Summary
    summary: Optional[str] = None
    highlightedValue: Optional[str] = None

    # KPIs
    marginLabel: Optional[str] = None
    marginValue: Optional[str] = None
    cacLabel: Optional[str] = None
    cacValue: Optional[str] = None

    # Trajectory
    trajectoryTitle: Optional[str] = None
    trajectoryData: Optional[List[Dict[str, Any]]] = None
    recordHighLabel: Optional[str] = None

    # Drivers
    drivers: Optional[List[InfographicDataDriver]] = None

    # Why
    whyTitle: Optional[str] = None
    whyContent: Optional[str] = None
    whyChartData: Optional[List[Dict[str, Any]]] = None

    # Strategic
    strategicTitle: Optional[str] = None
    strategicContent: Optional[str] = None

    # Outlook
    outlookTitle: Optional[str] = None
    outlookContent: Optional[str] = None
    outlookChartData: Optional[List[Dict[str, Any]]] = None
    outlookChartCenterValue: Optional[str] = None
    outlookChartCenterLabel: Optional[str] = None


class GenerateInfographicRequest(BaseModel):
    """Request to generate structured infographic data."""

    question: str
    answer: str
    data_sample: Optional[List[Dict[str, Any]]] = None
    language: str = "en"
    style: str = "mix"  # textual, visual, mix


class GenerateInfographicResponse(BaseModel):
    """Response with structured infographic data."""

    data: InfographicData
    timestamp: datetime
