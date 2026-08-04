"""Conteúdo dos passos 1 e 2 do fluxo da demo (FE-06).

Servido de um ficheiro JSON e não de tabelas, ao contrário do BE-12. A
diferença é o que o conteúdo é: os insights e as respostas curadas são
derivados de dados reais e verificados contra SQL, portanto ganham em
viver na base ao lado do que os produziu. Isto são quatro parágrafos
editoriais e uma lista de conectores — não têm origem em dados, não são
verificáveis contra nada, e mudam quando alguém decide que uma frase
convence mais. Uma migração para os guardar seria cerimónia sem
benefício, e tornaria mais lento exactamente o tipo de alteração que se
vai querer fazer muitas vezes.

O ficheiro é lido uma vez e guardado em memória. Em produção o pod
reinicia num deploy, que é quando o conteúdo muda de qualquer maneira.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONTENT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "demo" / "flow_content.json"

# Quantas perguntas o passo 2 mostra. Três é o que cabe sem o ecrã
# passar de "olha o que isto responde" para "olha esta lista".
UNLOCKED_LIMIT = 3


@lru_cache(maxsize=1)
def _content() -> Dict[str, Any]:
    try:
        return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        # Sem conteúdo, o fluxo tem de continuar a andar: o passo 1
        # perde o gancho mas não bloqueia ninguém. Um ecrã de erro à
        # entrada de uma demo comercial custa a visita inteira.
        logger.error("demo_flow_content_unreadable: %s", exc)
        return {"verticals": [], "sources": [], "source_reply": {}}


def list_verticals() -> List[Dict[str, str]]:
    """Opções do passo 1, cada uma com o seu gancho.

    O gancho vem já com a opção: o frontend mostra-o assim que a pessoa
    escolhe, sem uma segunda ida ao servidor. Uma pausa de rede entre o
    clique e a recompensa desfaz precisamente o efeito que se procura.
    """
    return [
        {
            "id": v["id"],
            "label": v["label"],
            "hook_markdown": v.get("hook_markdown", ""),
        }
        for v in _content().get("verticals", [])
    ]


def list_sources() -> List[Dict[str, Any]]:
    """Conectores do passo 2."""
    return [
        {"id": s["id"], "label": s["label"], "supported": bool(s.get("supported", True))}
        for s in _content().get("sources", [])
    ]


def unlocked_questions(
    source_ids: Optional[List[str]] = None, vertical: Optional[str] = None
) -> Dict[str, Any]:
    """A resposta do passo 2: o que passa a ter resposta.

    Devolve sempre exactamente :data:`UNLOCKED_LIMIT` perguntas,
    completando com as genéricas quando as fontes escolhidas não dão
    para tantas. Um ecrã que prometia três e mostra uma parece avariado.

    ``unknown`` ("não sei bem") não é um caso de erro — tem texto
    próprio de acolhimento. Obrigar um decisor a fingir que sabe onde
    vivem os dados da empresa é a forma mais rápida de o perder.
    """
    reply = _content().get("source_reply", {})
    ids = [s for s in (source_ids or []) if s]

    only_unknown = ids == ["unknown"]
    intro = (
        reply.get("intro_unknown_markdown", "") if only_unknown else reply.get("intro_markdown", "")
    )

    by_source: Dict[str, List[str]] = reply.get("questions_by_source", {}) or {}
    picked: List[str] = []
    # Alternar entre fontes em vez de esgotar a primeira: quem escolheu
    # Postgres e Excel deve ver que ambas contam, não três perguntas de
    # Postgres.
    for rank in range(3):
        for sid in ids:
            options = by_source.get(sid) or []
            if rank < len(options) and options[rank] not in picked:
                picked.append(options[rank])
            if len(picked) >= UNLOCKED_LIMIT:
                break
        if len(picked) >= UNLOCKED_LIMIT:
            break

    for fallback in reply.get("questions_default", []):
        if len(picked) >= UNLOCKED_LIMIT:
            break
        if fallback not in picked:
            picked.append(fallback)

    return {
        "intro_markdown": intro,
        "unlocked_intro": reply.get("unlocked_intro", ""),
        "questions": picked[:UNLOCKED_LIMIT],
    }


__all__ = ["UNLOCKED_LIMIT", "list_sources", "list_verticals", "unlocked_questions"]
