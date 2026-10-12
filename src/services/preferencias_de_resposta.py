"""O que a pessoa escreveu no Perfil chega à Sky.

A app grava em ``users.preferences`` duas coisas (``PUT /settings``):

- ``nickname`` — «¿Cómo debemos llamarle?»
- ``response_preferences`` — «¿Qué preferencias debe tener en cuenta Sky?»
  (texto livre: tamanho, formato, o que for)

Nada as lia (auditoria da app, 12/10/2026): o ecrã prometia «se aplicará a
todas las conversaciones» e era falso. O sky-ai já aceita ``instructions``
(texto livre que chega ao formatador como «ADDITIONAL INSTRUCTIONS»), por
isso não é preciso nenhum campo novo no motor — basta juntá-las aí, nos
caminhos que perguntam: ``/ai/chat/stream`` (app) e ``/ai/query`` (web).

**Limites, de propósito.** É texto da própria pessoa a moldar as respostas
DELA, e por isso o risco é baixo — mas vai cortado e enquadrado como
preferência de forma, para não se ler como uma ordem que passa por cima das
regras de acesso aos dados.
"""

from __future__ import annotations

from typing import Any, Optional

#: Cortes. Uma preferência de forma não precisa de mais; um texto enorme
#: era só contexto pago em cada pergunta.
MAX_APELIDO = 60
MAX_PREFERENCIAS = 500


def _texto(valor: Any, limite: int) -> str:
    if isinstance(valor, dict):
        # Uma app futura pode mandar {length: "short", format: "bullets"}.
        valor = "; ".join(f"{k}: {v}" for k, v in valor.items() if v not in (None, ""))
    if not isinstance(valor, str):
        return ""
    return " ".join(valor.split())[:limite]


def apelido(prefs: Optional[dict]) -> str:
    """Como a pessoa quer ser tratada, ou ``""``."""
    if not isinstance(prefs, dict):
        return ""
    return _texto(prefs.get("nickname"), MAX_APELIDO)


def instrucoes_de_resposta(prefs: Optional[dict]) -> str:
    """O bloco a juntar às ``instructions`` do motor, ou ``""``."""
    if not isinstance(prefs, dict):
        return ""
    partes = []
    nome = apelido(prefs)
    if nome:
        partes.append(f"Address the user as \"{nome}\" when greeting or addressing them directly.")
    pref = _texto(prefs.get("response_preferences"), MAX_PREFERENCIAS)
    if pref:
        partes.append(
            "The user's own preferences for the FORM of answers (length, format, "
            "tone). Follow them when they do not conflict with data accuracy or "
            f"access rules: {pref}"
        )
    if not partes:
        return ""
    return "USER RESPONSE PREFERENCES:\n" + "\n".join(f"- {p}" for p in partes)


def juntar(instrucoes: Optional[str], prefs: Optional[dict]) -> str:
    """``instrucoes`` com as preferências no fim (ou só elas)."""
    bloco = instrucoes_de_resposta(prefs)
    base = instrucoes or ""
    if not bloco:
        return base
    return f"{base}\n\n{bloco}" if base else bloco
