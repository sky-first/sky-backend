"""A primeira corrida de um agente acabado de criar conta UMA vez.

``POST /agents/`` já põe a estreia na fila (para quem criou ver logo um
resultado). A app, logo a seguir, chamava ``POST /agents/{id}/run`` — e o
agente corria duas vezes, gastando duas perguntas do plano (auditoria da app,
12/10/2026).

A criação deixa uma marca de vida curta; o primeiro ``/run`` que a encontra
**consome-a** e não volta a pôr a corrida na fila (responde como se tivesse
posto, com ``already_queued: true``). Um segundo toque em «Executar agora»
já não encontra marca e corre — é um pedido explícito, não um duplicado.

Sem Redis a marca não existe e tudo se comporta como antes (corre duas
vezes): falha aberta, porque recusar uma corrida pedida seria pior.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Tempo em que um ``/run`` ainda é «o da criação». A app chama-o logo a
#: seguir; passado isto, é um pedido novo.
TTL_SEGUNDOS = 120


def _chave(agent_id) -> str:
    return f"agent:estreia-na-fila:{agent_id}"


async def _redis():
    try:
        from src.config.redis import get_redis

        return await get_redis()
    except Exception:  # noqa: BLE001
        return None


async def marcar(agent_id) -> None:
    """Chamado quando a criação pôs a estreia na fila."""
    r = await _redis()
    if r is None:
        return
    try:
        await r.set(_chave(agent_id), "1", ex=TTL_SEGUNDOS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("estreia: marca não gravada para %s: %s", agent_id, exc)


async def ja_esta_na_fila(agent_id) -> bool:
    """True (uma única vez) se a estreia deste agente já está na fila."""
    r = await _redis()
    if r is None:
        return False
    try:
        return bool(await r.delete(_chave(agent_id)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("estreia: marca ilegível para %s: %s", agent_id, exc)
        return False
