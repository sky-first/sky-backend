"""Correr codigo assincrono a partir de uma tarefa do Celery, sem envenenar
a proxima.

**O defeito.** Nenhum agente do Lucas corria. Nos registos do worker de
producao, a partir da SEGUNDA tarefa do mesmo processo:

    Agent execution failed: Task ... got Future ... attached to a different loop

Tres falhas seguidas e o agente auto-pausa. E foi por isso que ele viu
«Paused. It won't look until you resume it» em agentes que nunca tinha
pausado, e «Running, but hasn't found anything yet» nos outros.

**A causa.** Cada tarefa criava um laco de eventos NOVO
(`asyncio.new_event_loop()`), corria, e fechava-o. Mas as ligacoes as bases
dos clientes vivem numa cache GLOBAL do processo — e uma ligacao do asyncpg
fica presa ao laco onde nasceu. A primeira tarefa criava as ligacoes no laco
A; o laco A fechava; a segunda tarefa reutilizava-as no laco B e rebentava.

A primeira tarefa depois de cada arranque do worker funcionava. E o que faz
isto tao mau de apanhar: reiniciar o pod «resolve» o problema durante uma
corrida.

── Porque se fecham as ligacoes e nao se reaproveita o laco ─────────────────

A alternativa era manter um laco por processo e reutiliza-lo. Fica mais
rapido e traz um problema pior: um laco de vida longa dentro de um worker
com fork guarda estado entre tarefas, e uma tarefa que o deixe sujo estraga
todas as seguintes — que e a familia de defeito que estamos aqui a corrigir,
so que mais dificil de ver.

Reabrir uma ligacao a base custa dezenas de milissegundos. Um agente corre
uma vez por hora, na melhor das hipoteses. Nao ha aqui nada a poupar.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def correr(coro):
    """Corre a corrotina num laco proprio e DEVOLVE as ligacoes ao sair.

    O `dispose` tem de acontecer DENTRO do laco — depois de ele fechar ja nao
    ha onde correr o fecho das ligacoes, e ficavam presas na mesma.
    """

    async def _com_limpeza():
        try:
            return await coro
        finally:
            # Sem isto, as ligacoes abertas neste laco ficam na cache global e
            # a proxima tarefa herda-as ja mortas. E o defeito inteiro.
            try:
                from src.config.tenant_connection_manager import (
                    tenant_connection_manager,
                )

                await tenant_connection_manager.dispose_all()
            except Exception as exc:  # noqa: BLE001
                # Falhar a fechar nao pode perder o resultado da tarefa, que
                # ja esta feito. Mas tem de aparecer: uma limpeza que falha em
                # silencio traz o defeito de volta sem deixar rasto.
                logger.warning("celery_dispose_falhou: %s", exc)

    laco = asyncio.new_event_loop()
    try:
        return laco.run_until_complete(_com_limpeza())
    finally:
        laco.close()
