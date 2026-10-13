"""Tarefas das fontes do sistema (dados públicos geridos pela Sky).

- ``provisionar_fontes_do_cliente(slug)`` — enfileirada pela Consola a cada
  marcar/desmarcar e pelo hook de projecto novo. Converge o cliente inteiro
  (não uma fonte): é idempotente e lê o estado desejado no fim (S17).
- ``reconciliar_fontes_sistema()`` — Beat de hora a hora: converge todos os
  clientes com fontes e avisa de papéis ``wt_*`` órfãos (S20).
- ``remover_cliente_do_mundo(slug)`` — destruição do cliente.

O cliente vem SEMPRE por argumento. A tarefa não depende do contextvar que
o ``task_prerun`` repõe a partir do cabeçalho: entra em
``contexto_do_cliente(slug)`` e manda ``X-Tenant-Slug`` explícito ao sky-ai.
"""

from __future__ import annotations

import logging

from src.config.settings import settings
from src.workers.celery_app import celery_app
from src.workers.laco_do_celery import correr

logger = logging.getLogger(__name__)


@celery_app.task(name="src.workers.fontes_sistema_worker.provisionar_fontes_do_cliente")
def provisionar_fontes_do_cliente(slug: str) -> dict:
    from src.services.fontes_sistema.provisionamento import convergir_cliente

    resumo = correr(convergir_cliente(slug))
    logger.info("fontes_sistema[%s]: %s", slug, {k: v for k, v in resumo.items() if k != "tabelas"})
    return resumo


@celery_app.task(name="src.workers.fontes_sistema_worker.reconciliar_fontes_sistema")
def reconciliar_fontes_sistema() -> dict:
    if not settings.FONTES_SISTEMA_ENABLED:
        return {"estado": "funcionalidade_desligada"}

    async def _tudo() -> dict:
        from src.services.fontes_sistema import provisionamento as p

        async with p._sessao_plataforma() as s:
            slugs = await p.clientes_com_fontes(s)
        feitos, falhados = 0, 0
        for slug in slugs:
            try:
                r = await p.convergir_cliente(slug)
                if r.get("erro"):
                    falhados += 1
                else:
                    feitos += 1
            except Exception as exc:  # noqa: BLE001 — um cliente não trava os outros
                falhados += 1
                logger.warning("fontes_sistema[%s]: reconciliação falhou: %s", slug, exc)
        orfaos: list = []
        try:
            orfaos = await p.papeis_orfaos()
        except Exception as exc:  # noqa: BLE001
            logger.warning("fontes_sistema: não consegui listar papéis órfãos: %s", exc)
        if orfaos:
            logger.error(
                "fontes_sistema: papéis sem cliente vivo em sky_world: %s — "
                "credencial órfã com acesso a dados pagos; remover com "
                "remover_cliente_do_mundo",
                orfaos,
            )
        return {"clientes": len(slugs), "ok": feitos, "falhados": falhados, "orfaos": orfaos}

    return correr(_tudo())


@celery_app.task(name="src.workers.fontes_sistema_worker.remover_cliente_do_mundo")
def remover_cliente_do_mundo(slug: str) -> dict:
    if not settings.FONTES_SISTEMA_ENABLED:
        return {"estado": "funcionalidade_desligada"}
    from src.services.fontes_sistema.provisionamento import remover_cliente

    correr(remover_cliente(slug))
    return {"slug": slug, "estado": "removido"}
