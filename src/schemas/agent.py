from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.agent import AgentArchetype, AgentFrequency, AgentScope, AgentStatus, FindingSeverity, FindingType


# Phase 4.2: explicit set of agent monitor types the platform supports.
# Kept as a tuple (not an Enum) because `datasource` is a legacy alias
# for `scan` — Pydantic Enums reject aliases, a validator does not.
# Clients still writing `datasource` keep working; new writers should
# prefer `scan`. `context` is reserved for Phase 5 (full-context mode).
MONITOR_TYPE_VALUES: tuple[str, ...] = (
    "question",
    "sql",
    "scan",
    "datasource",
    "context",
    "insight",
)


def _validate_monitor_type(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s not in MONITOR_TYPE_VALUES:
        raise ValueError(
            f"monitor_type must be one of {MONITOR_TYPE_VALUES}, got {v!r}"
        )
    return s


# ─── Agent schemas ───

class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    archetype: AgentArchetype = AgentArchetype.CUSTOM
    scope: AgentScope = AgentScope.SPACE
    # Optional because the personal-mode wizard does not always have a
    # scope_id at submission time. The service layer normalises personal
    # agents to scope_id == user.id, so accepting None here keeps the
    # invariant without forcing the FE to fabricate a placeholder.
    scope_id: Optional[str] = Field(default=None, max_length=255)
    scope_name: Optional[str] = Field(None, max_length=255)
    monitor_type: str = Field("question", max_length=20)
    focus: Optional[str] = None  # The question or instructions
    custom_sql: Optional[str] = None  # For sql monitor_type
    frequency: AgentFrequency = AgentFrequency.DAILY
    depth: Optional[str] = Field("standard", max_length=20)
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None  # Granular table selection
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    # Transcript from the AI chat when the agent was created via the
    # "Create agent from this chat" CTA. Plain text, nullable.
    chat_context: Optional[str] = None
    # Full Universe-Intelligence scope: dict keyed by entity kind. After
    # the Knowledge refactor (Phase 1) the kinds are: glossary_terms (and
    # metrics in Phase 2), enterprise_relationships, widgets, insights,
    # pages. Empty arrays or missing keys = "no filter for that kind".
    selected_context: Optional[Dict[str, List[str]]] = None
    # Phase 6 — when true the agent runtime drops every connection whose
    # tier ≠ 'internal' before issuing the query. Compliance-bound deploys
    # opt in here so autonomous agents only touch low-risk data sources.
    auditable_only: Optional[bool] = False

    @field_validator("monitor_type")
    @classmethod
    def _check_monitor_type(cls, v):
        return _validate_monitor_type(v) or "question"


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    monitor_type: Optional[str] = Field(None, max_length=20)
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    frequency: Optional[AgentFrequency] = None
    depth: Optional[str] = Field(None, max_length=20)
    table_ids: Optional[List[str]] = None
    connection_ids: Optional[List[UUID]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    chat_context: Optional[str] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    # Flexible schedule — supersedes `frequency` when present.
    # Shape: {interval_value: int, interval_unit: minute|hour|day|week|month,
    #         end: {type: forever|once|n_runs|until_date, value: int|iso?}}
    schedule_jsonb: Optional[Dict[str, Any]] = None
    # Phase 6 — auditable_only toggle. See AgentCreate for semantics.
    auditable_only: Optional[bool] = None

    @field_validator("monitor_type")
    @classmethod
    def _check_monitor_type(cls, v):
        return _validate_monitor_type(v)


#: O que ja esta gravado na base e nao e um valor do enum, e o valor certo.
#:
#: O classificador do `sky-ai` escreveu `med` durante dois dias — o enum
#: chama-lhe `medium`. Cada achado assim gravado rebentava o `GET
#: /agents/{id}` inteiro com um `ResponseValidationError`, e o ecra do agente
#: dava 500 sem nada a explicar.
#:
#: **Tolerante a leitura, estrito a escrita.** A escrita ja foi corrigida nos
#: dois servicos; isto e para as linhas que ficaram. Rejeitar na leitura
#: castiga quem le por um erro de quem escreveu — e o achado esta na base,
#: correcto, so com a palavra errada.
_GRAVIDADES_ANTIGAS = {"med": "medium", "mid": "medium", "moderate": "medium"}


class AgentFindingResponse(BaseModel):
    id: UUID
    agent_id: UUID
    type: FindingType
    severity: FindingSeverity

    @field_validator("severity", mode="before")
    @classmethod
    def _gravidade_antiga(cls, v):
        return _GRAVIDADES_ANTIGAS.get(str(v).lower().strip(), v)
    title: str
    description: str
    confidence: Optional[float] = None
    query: Optional[str] = None
    evidence: Optional[str] = None
    reasoning: Optional[str] = None
    recommendation: Optional[str] = None
    data_sources: Optional[List[Optional[str]]] = None
    rows: Optional[Dict[str, Any]] = None  # {columns, data, truncated?} — consumed by Cockpit
    # Sprint 1.17 round 5 — visualisation hint the Pulse FE uses to
    # pick the card variant + the widget kind on "Add to page".
    viz_kind: Optional[str] = None
    connection_id: Optional[UUID] = None
    connection_name: Optional[str] = None
    dismissed: bool = False
    created_at: datetime

    # Origin metadata — populated by GET /agents/insights/all so the global
    # Pulse feed (topbar chip + panel) can badge each finding with where it
    # came from (space › crew › page) and deep-link the user to it. Left None
    # on the per-agent findings endpoint, where the origin is already implicit.
    agent_name: Optional[str] = None
    scope: Optional[str] = None
    scope_id: Optional[str] = None
    scope_name: Optional[str] = None
    space_id: Optional[str] = None
    space_name: Optional[str] = None
    page_id: Optional[UUID] = None
    page_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AgentExecutionResponse(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    cycles_consumed: int
    findings_count: int
    error_message: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AgentResponse(BaseModel):
    id: UUID
    name: str
    archetype: str
    scope: str
    scope_id: str
    scope_name: Optional[str] = None
    status: str
    monitor_type: str = "question"
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    chat_context: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    auditable_only: bool = False
    # A conversa onde este agente escreve.
    #
    # A coluna existe no modelo desde sempre; o que faltava era devolvê-la. A
    # app usa-a para mostrar "Abrir conversa" — que o comentário dela descreve
    # como *"a mais usada de todas"* — e, sem o campo, **todos** os agentes
    # apareciam como "Ainda não falou", mesmo os que já tinham corrido e
    # produzido achados. O botão nunca chegava a existir.
    #
    # Apanhado a 20/08 comparando o que cada rota devolve com o tipo que a app
    # declara — o mesmo método que destapou o `connection_id` e o `user`
    # aninhado dos membros nesse dia.
    conversation_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    # ── O que este agente ANDOU A FAZER ──────────────────────────────────
    #
    # A lista de agentes devolvia o que cada um É — nome, pergunta, cadência —
    # e nada sobre o que ele TEM FEITO. No ecrã isso lê-se como uma tabela de
    # tarefas agendadas: nomes e horários, sem sinal de vida.
    #
    # Estes três campos são o que transforma a lista numa equipa a trabalhar:
    # o que encontrou da última vez, quando, e se a última corrida correu bem.
    #
    # Saem de duas consultas agregadas na listagem — uma pelo último achado,
    # outra pela última execução — e não de um `N+1` por agente.
    last_finding_title: Optional[str] = None
    last_finding_at: Optional[datetime] = None
    #: `completed`, `failed`, `running` — ou `None` se nunca correu.
    #:
    #: Um agente ACTIVO que falha em silêncio é pior do que um parado: o
    #: parado diz que está parado. Sem isto, os dois liam-se igual.
    last_run_status: Optional[str] = None

    # Nested — only included when fetching single agent
    findings: Optional[List[AgentFindingResponse]] = None
    # Option B: True when the caller may SEE the agent (management) but its
    # findings/insights were withheld because they are not a crew/space member.
    # Lets the UI render an "ask to be added" mask instead of "no insights".
    findings_restricted: bool = False

    model_config = ConfigDict(from_attributes=True)


class AddFindingToPageRequest(BaseModel):
    """Payload for POST /agents/{agent_id}/findings/{finding_id}/add-to-page.

    The finding is materialised as a Widget on the target page. The
    server picks the widget ``type`` from ``finding.viz_kind`` (see
    `_viz_kind_to_widget_type` in agent_service); the caller optionally
    pins position/size, otherwise defaults are applied.
    """

    page_id: UUID
    position: Optional[Dict[str, float]] = None
    size: Optional[Dict[str, float]] = None


class AddFindingToPageResponse(BaseModel):
    """Response after materialising a finding on a page — returns the
    new Widget id so the FE can navigate / scroll to it."""

    widget_id: UUID
    page_id: UUID
    finding_id: UUID
    widget_type: str


class AgentListResponse(BaseModel):
    """Lightweight response for list/mutation endpoints — agent metadata only.

    Findings are NOT included here. The list endpoint (``GET /api/v1/agents/``)
    deliberately does not eager-load ``Agent.findings`` to keep DB connection
    pool usage bounded (see commit 46623cf: 62 concurrent list calls each
    doing ``selectinload(findings)`` were exhausting the pool). Because the
    relationship is async-lazy, leaving ``findings`` on this response triggered
    a Pydantic ``get_attribute_error`` (MissingGreenlet) during serialization
    of the un-loaded relationship → 500 to the client.

    Callers that need findings should use ``GET /api/v1/agents/{agent_id}``
    (``AgentResponse``), which goes through ``get_with_findings``.
    """
    id: UUID
    name: str
    archetype: str
    scope: str
    scope_id: str
    scope_name: Optional[str] = None
    status: str
    monitor_type: str = "question"
    focus: Optional[str] = None
    custom_sql: Optional[str] = None
    chat_context: Optional[str] = None
    frequency: str
    depth: Optional[str] = None
    connection_ids: List[UUID] = []
    table_ids: Optional[List[str]] = None
    selected_context: Optional[Dict[str, List[str]]] = None
    space_ids: Optional[List[UUID]] = None
    relationship_types: Optional[List[str]] = None
    last_execution_at: Optional[datetime] = None
    next_execution_at: Optional[datetime] = None
    executions_this_month: int = 0
    cycles_consumed: int = 0
    auditable_only: bool = False
    # A conversa onde o agente escreve — **também aqui**.
    #
    # Pus isto no `AgentResponse` e promovi, e o botão continuou a não
    # aparecer: o ecrã dos agentes lê a LISTA, e a lista usa este outro
    # schema. Metade da correcção foi para o sítio errado, e só se viu ao
    # verificar em produção com uma conta a sério em vez de dar por feito.
    conversation_id: Optional[UUID] = None
    created_at: datetime

    # ── OS SINAIS DE VIDA — **também aqui**. ─────────────────────────────
    #
    # É o mesmo erro que o comentário logo acima descreve, com outros campos.
    # Pu-los no `AgentResponse` (o detalhe) e o repositório preenche-os na
    # LISTAGEM — mas este schema não os declarava, e o Pydantic deita fora o
    # que não declara.
    #
    # Resultado no ecrã: TODOS os agentes diziam «A correr, mas ainda não
    # encontrou nada», incluindo um com 22 descobertas no feed. A app não
    # estava enganada: o servidor nunca lhe mandou o campo.
    #
    # Apanhei-o a olhar para a resposta crua do `/agents` — as três chaves
    # não vinham a `null`, não vinham de todo.
    last_finding_title: Optional[str] = None
    last_finding_at: Optional[datetime] = None
    #: `completed`, `failed`, `running` — ou `None` se nunca correu.
    #:
    #: Um agente ACTIVO que falha em silêncio é pior do que um parado: o
    #: parado diz que está parado. Sem isto, os dois liam-se igual.
    last_run_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
