"""Schemas for the unified mobile Insights feed (BE-02, Sky Mobile).

The feed serves one machine-readable object per finding — agent-produced or
scan-produced — with the two typed axes the mobile UI renders (``severity``
dot + ``severity_level``), the sparkline ``series``, and the caller's own
``reviewed``/``pinned`` state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# The five filter chips the design ships.
# Os mesmos cortes que a web oferece no seu painel, para os dois clientes
# mostrarem as mesmas listas com os mesmos nomes.
#
# `new` e `reviewed` são POR PESSOA (vivem no `InsightState`), e é isso que os
# torna úteis: «novo» quer dizer novo para quem está a ver, não novo no mundo.
#
# `latest` e `featured` ficam por compatibilidade — `latest` é, e sempre foi,
# idêntico a `all`. Ver a nota no `_apply_filter`.
INSIGHT_FILTERS = (
    "all",
    "new",
    "reviewed",
    "pinned",
    "risk",
    "opportunity",
    "insight",
    "latest",
    "featured",
)


class InsightItem(BaseModel):
    id: str
    severity: str  # AgentFinding.type: risk | opportunity | insight
    severity_level: str  # AgentFinding.severity: high | med | low
    agent_name: Optional[str] = None
    title: str
    summary: str
    is_live: bool
    series: List[Dict[str, Any]] = []
    created_at: datetime
    reviewed: bool = False
    pinned: bool = False
    deep_link: str
    # A conversa do agente que produziu este achado.
    #
    # E o que permite ao cliente abrir o FIO ao tocar no insight, em vez de uma
    # pagina estatica: o insight e uma mensagem de uma conversa, e a conversa e
    # onde se pergunta "explica melhor" ou "e agora o Norte?". None quando o
    # achado nao veio de um agente com conversa (achados antigos, varreduras).
    conversation_id: Optional[str] = None


class InsightFeedResponse(BaseModel):
    items: List[InsightItem]
    next_cursor: Optional[str] = None
    # Per-filter counts over the caller's full scope, so the chips are exact.
    counts: Dict[str, int]


class InsightDetail(InsightItem):
    description: str
    stat_tiles: List[Dict[str, Any]] = []
    viz_kind: Optional[str] = None


class ReviewRequest(BaseModel):
    reviewed: bool


class PinRequest(BaseModel):
    pinned: bool


class ReclassificarRequest(BaseModel):
    """Corrigir a classificação de um achado.

    A Sky classifica ao gravar; isto é a correcção de quem discorda. Vale mais
    do que a adivinhação inicial — quem está a ver o achado sabe se aquilo é
    mesmo um risco.

    Ao contrário do «visto» e do «fixado», isto NÃO é por pessoa: a
    classificação é do achado e muda para toda a gente. Um risco não é risco
    só para mim.
    """

    type: Optional[str] = Field(
        default=None, description="risk | opportunity | insight"
    )
    severity: Optional[str] = Field(default=None, description="high | med | low")
