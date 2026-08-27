"""Uma recusa da IA não é um achado.

> *"Notificação com o **texto de recusa** da IA em vez de um achado."*
> — Lucas, item 7.2

**O que acontecia.** O worker do agente gravava um achado sempre que a IA
devolvesse **alguma coisa**::

    uteis = [r for r in por_ligacao if (r.get("answer") or "").strip()]

Uma recusa — *"Nenhuma fonte de dados disponível para este chat."* — é uma
resposta não vazia. Passava o filtro, virava um achado com esse texto por
descrição, e o telemóvel acordava a pessoa com uma notificação a dizer que o
agente tinha descoberto uma coisa. A coisa era a máquina a dizer que não podia
responder.

Pior do que ruído: **ensina a ignorar as notificações dos agentes**, que são a
razão de os agentes existirem.

**Como se reconhece.** Pelo catálogo — `src/core/locale.py` — e não por
adivinhação. As frases de recusa são escritas pelo próprio servidor, estão lá
todas, e em todas as línguas. Comparar contra a fonte é a única maneira de
isto não ficar desactualizado no dia em que alguém mudar uma frase.

**O que NÃO se faz aqui.** Não se tenta perceber se a IA *quis* recusar por
outras palavras. Um modelo pode dizer «não encontrei nada relevante» e isso é
uma resposta legítima a uma pergunta legítima — pode até ser o achado («as
vendas não mudaram»). Só se apanha o que o **servidor** escreveu como recusa;
o resto passa.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: As chaves do catálogo que são recusas — não respostas.
#:
#: Ficam nomeadas uma a uma de propósito: o catálogo tem muitas frases, e a
#: maioria — saudações, «a pensar…», títulos de notificação — não tem nada a
#: ver com isto. Uma lista negativa («tudo menos estas») apanharia o
#: «Como posso ajudar?» e passaria a descartar respostas boas.
_CHAVES_DE_RECUSA = (
    "space_has_no_data_can_connect",
    "space_has_no_data_ask_access",
    "no_data_source",
    "no_data_source_agent",
    "unable_to_start_stream",
    # A IA não percebeu a pergunta — também não é um achado.
    "couldnt_understand",
    # Uma pergunta vazia nunca devia chegar a um agente, mas se chegar a
    # resposta é a mesma frase feita.
    "empty_message",
)


def _frases_de_recusa() -> set[str]:
    """As frases exactas, em todas as línguas, lidas do catálogo."""
    from src.core.locale import _MESSAGES

    frases: set[str] = set()
    for chave in _CHAVES_DE_RECUSA:
        traducoes = _MESSAGES.get(chave)
        if not isinstance(traducoes, dict):
            continue
        for frase in traducoes.values():
            if isinstance(frase, str) and frase.strip():
                frases.add(frase.strip().lower())
    return frases


def e_uma_recusa(resposta: str | None) -> bool:
    """A IA recusou-se a responder?

    Compara com o catálogo do servidor. Uma resposta que **comece** por uma
    frase de recusa conta — algumas levam uma instrução a seguir («…e eu
    respondo com base nela»), e o worker corta o texto a 3000 caracteres, por
    isso comparar por igualdade exacta falhava metade das vezes.
    """
    texto = (resposta or "").strip().lower()
    if not texto:
        return False
    for frase in _frases_de_recusa():
        if texto.startswith(frase) or frase in texto:
            return True
    return False


def respostas_que_sao_achados(por_ligacao: list[dict]) -> list[dict]:
    """Filtra as recusas de uma lista de respostas por ligação.

    Devolve só o que é achado. Uma lista vazia quer dizer «esta corrida não
    encontrou nada» — que é um resultado legítimo e não um erro: o agente
    correu, olhou, e não havia nada a dizer.
    """
    achados = []
    for r in por_ligacao:
        if e_uma_recusa(r.get("answer")):
            logger.info(
                "agente: resposta descartada por ser uma recusa (ligação %s)",
                r.get("conn_id"),
            )
            continue
        achados.append(r)
    return achados
