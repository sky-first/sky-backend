"""Contratos públicos da demo curada — BE-12.

Servem quatro endpoints sem autenticação. Nenhum deles expõe dados de
tenants reais: tudo o que sai daqui é conteúdo curado sobre datasets
sintéticos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


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
    chart_spec: Optional[Dict[str, Any]] = None
    executed_sql: Optional[str] = None
    # Verdadeiro quando a resposta veio do banco curado por a geração ao
    # vivo ter excedido o tempo. O frontend tem de o dizer ao visitante —
    # apresentar conteúdo de exemplo como se fosse sobre os dados dele
    # seria enganador.
    is_fallback: bool = False


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
