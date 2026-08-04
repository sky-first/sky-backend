"""Contratos públicos da demo curada — BE-12.

Servem quatro endpoints sem autenticação. Nenhum deles expõe dados de
tenants reais: tudo o que sai daqui é conteúdo curado sobre datasets
sintéticos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class StatTile(BaseModel):
    label: str
    value: str


class SourceRef(BaseModel):
    table: str
    description: Optional[str] = None


class SeriesPoint(BaseModel):
    t: str
    v: float


class DemoInsightModel(BaseModel):
    """O bloco herói do primeiro ecrã."""

    id: str
    severity: str
    severity_level: str
    agent_name: str
    title: str
    summary: str
    series: Optional[List[SeriesPoint]] = None
    stat_tiles: List[StatTile] = Field(default_factory=list)
    sources: List[SourceRef] = Field(default_factory=list)
    # O "ver o SQL" — o elemento de prova mais barato do ecrã.
    executed_sql: Optional[str] = None


class SuggestedQuestion(BaseModel):
    id: str
    question: str


class DemoBootstrapResponse(BaseModel):
    dataset_id: str
    vertical: str
    locale: str
    insight: Optional[DemoInsightModel] = None
    suggested_questions: List[SuggestedQuestion] = Field(default_factory=list)


class DemoAnswerResponse(BaseModel):
    id: str
    question: str
    answer_markdown: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    stat_tiles: List[StatTile] = Field(default_factory=list)
    chart_spec: Optional[Dict[str, Any]] = None
    executed_sql: Optional[str] = None
    # Verdadeiro quando a resposta veio do banco curado por a geração ao
    # vivo ter excedido o tempo. O frontend tem de o dizer ao visitante —
    # apresentar conteúdo de exemplo como se fosse sobre os dados dele
    # seria enganador.
    is_fallback: bool = False
    # A pergunta não é sobre dados de negócio. Distinto de `is_fallback`:
    # ali servimos conteúdo aproximado, aqui não servimos nada e
    # dizemo-lo. O texto vive no frontend, que sabe o idioma do
    # visitante — o backend diz o que aconteceu, não em que língua.
    out_of_domain: bool = False


class DemoAskRequest(BaseModel):
    dataset_id: str
    question: str = Field(..., min_length=3, max_length=500)


class DemoLeadRequest(BaseModel):
    # EmailStr valida a forma. Deliberadamente **sem** lista de domínios
    # bloqueados: o filtro de "throwaway providers" da demo antiga barrava
    # clientes reais que usam gmail como email de empresa.
    email: EmailStr
    dataset_id: Optional[str] = None
    questions_asked: List[str] = Field(default_factory=list)
    vertical: Optional[str] = None
    locale: Optional[str] = None
    source: Optional[str] = Field(default=None, max_length=64)


class DemoLeadResponse(BaseModel):
    accepted: bool = True


__all__ = [
    "DemoAnswerResponse",
    "DemoAskRequest",
    "DemoBootstrapResponse",
    "DemoInsightModel",
    "DemoLeadRequest",
    "DemoLeadResponse",
    "SeriesPoint",
    "SourceRef",
    "StatTile",
    "SuggestedQuestion",
]


# ─── Fluxo de cinco passos (FE-06) ──────────────────────────────────


class DemoVertical(BaseModel):
    """Opção do passo 1, com o gancho já incluído.

    O gancho viaja com a opção de propósito: o frontend mostra-o assim
    que a pessoa clica, sem uma segunda ida ao servidor. Uma pausa de
    rede entre o clique e a recompensa desfaz o efeito que se procura.
    """

    id: str
    label: str
    hook_markdown: str = ""


class DemoSource(BaseModel):
    """Conector do passo 2."""

    id: str
    label: str
    supported: bool = True


class DemoUnlockedRequest(BaseModel):
    source_ids: List[str] = Field(default_factory=list)
    vertical: Optional[str] = None
    locale: Optional[str] = None


class DemoUnlockedResponse(BaseModel):
    """A devolução do passo 2 — o que passa a ter resposta."""

    intro_markdown: str = ""
    unlocked_intro: str = ""
    questions: List[str] = Field(default_factory=list)


class DemoFileQuestion(BaseModel):
    """Uma pergunta sobre o ficheiro que o visitante acabou de largar.

    Vai uma **amostra**, não o ficheiro. Não é só custo: um contexto
    gigante dilui a pergunta e piora a resposta. E o que sobe é
    transitório — usado para responder e nunca escrito em lado nenhum,
    o mesmo modelo do iLovePDF, cumprido por não existir código que
    escreva em vez de por uma limpeza que alguém tem de manter.
    """

    question: str = Field(min_length=2, max_length=500)
    locale: Optional[str] = None
    columns: List[str] = Field(default_factory=list, max_length=80)
    rows: List[List[str]] = Field(default_factory=list, max_length=200)
    total_rows: Optional[int] = None
    text: Optional[str] = Field(default=None, max_length=40_000)

    @field_validator("rows")
    @classmethod
    def _trim_rows(cls, rows: List[List[str]]) -> List[List[str]]:
        """Corta células absurdas antes de o conteúdo chegar ao modelo.

        O limite global de 1 MiB por pedido já impede o pior, e o motor
        corta a 120 linhas do seu lado. Isto é a terceira camada, e
        existe porque as outras duas estão noutro sítio: quem lê este
        endpoint tem de conseguir ver o que ele aceita sem ir procurar
        um middleware e um serviço noutro repositório.
        """
        return [[str(cell)[:400] for cell in row[:80]] for row in rows]


class DemoFileAnswer(BaseModel):
    answer: str = ""
    insufficient: bool = False
