"""AI schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageRequest(BaseModel):
    """Chat message request schema."""

    message: str = Field(..., min_length=1)
    widget_id: UUID
    context: Optional[Dict[str, Any]] = None


class ChatMessageResponse(BaseModel):
    """Chat message response schema."""

    id: UUID
    type: str  # user, assistant
    content: str
    timestamp: datetime

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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateHistoryRequest(BaseModel):
    """Create history request schema."""

    query: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    category: Optional[str] = None
    tags: Optional[List[str]] = Field(default_factory=list)


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


class ValidateSQLResponse(BaseModel):
    """Response da validação de SQL."""

    is_valid: bool = Field(..., description="Se o SQL é válido.")
    error: Optional[str] = Field(None, description="Mensagem de erro.")
    preview_data: Optional[List[Dict[str, Any]]] = Field(None, description="Preview dos dados.")
    num_rows: Optional[int] = Field(None, description="Número de linhas.")
    execution_time_ms: Optional[float] = Field(None, description="Tempo de execução.")
    columns: Optional[List[str]] = Field(None, description="Colunas retornadas.")
