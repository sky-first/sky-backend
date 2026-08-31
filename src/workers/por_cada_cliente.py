"""Correr uma tarefa periódica na base de CADA cliente, e não só na da plataforma.

**O defeito.** Os três agendadores — agentes, insights, varredura de órfãos —
abriam `AsyncSessionLocal()`, que é a base da **plataforma**, e procuravam lá
os agentes a correr.

No modelo B, os agentes de cada cliente vivem na base dedicada dele
(`tenant_gbtsolutions`, `tenant_skyfirstlabs`, `tenant_sandbox`). Na base da
plataforma não há agente nenhum de cliente nenhum.

Ou seja: mesmo com o `celery beat` a correr, o agendador percorreria uma base
vazia, escreveria «0 agentes vencidos» nos registos, e nada aconteceria. **É
pior do que não haver agendador**, porque parece que funciona: há um pod de pé,
há linhas nos registos, e a métrica diz zero — que é indistinguível de «não há
nada a fazer».

É a mesma família de defeito que já mordeu três vezes neste projeto (PRs
#569/#570/#571): código escrito antes do modelo B, que continua a olhar para a
base da plataforma como se fosse a única.

── Porque o contexto se define aqui e não dentro de cada tarefa ─────────────

O `execute_agent.delay(...)` leva o cliente nos cabeçalhos da mensagem, tirado
do `current_tenant()` no momento em que é posto na fila. Se o agendador
enfileirar sem contexto, a tarefa chega ao worker com «default» e vai procurar
o agente na base da plataforma — onde ele não está — e regista «Agent not
found».

Por isso o contexto tem de estar posto **enquanto** se enfileira, e não só
enquanto se lê. É a razão de isto ser um contexto e não um simples ciclo.

── O que isto NÃO faz ───────────────────────────────────────────────────────

Não corre em paralelo. Com dez clientes e uma passagem de 5 em 5 minutos, o
custo é uma ligação de cada vez durante uns segundos — e a alternativa,
abrir dez ligações ao mesmo tempo a partir do agendador, tem um custo real de
memória e de ligações no Postgres que ninguém pediu para pagar.

E **um cliente que falhe não trava os outros**. Uma base indisponível é um
cliente sem agentes durante cinco minutos; sem esta guarda seria toda a gente
sem agentes até alguém reparar.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, List, Tuple

logger = logging.getLogger(__name__)


async def clientes_activos() -> List[str]:
    """Os `slug` de cada cliente activo com base dedicada.

    Inclui a plataforma (o `default`) como primeiro elemento: há instalações
    de um cliente só, e nessas os agentes vivem mesmo lá. Excluí-la fazia o
    agendador ignorar exactamente esse caso.
    """
    from src.config.database import AsyncSessionLocal
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    slugs: List[str] = [DEFAULT_TENANT_CONTEXT.slug]
    try:
        from sqlalchemy import select

        from src.models.tenant import Tenant

        async with AsyncSessionLocal() as db:
            linhas = (
                await db.execute(select(Tenant).where(Tenant.is_active.is_(True)))
            ).scalars().all()
        for row in linhas:
            # Sem base dedicada, os dados dele estão na da plataforma — já
            # coberta acima. Somá-lo outra vez enfileirava tudo a dobrar.
            if not row.db_host or not row.db_name:
                continue
            if row.slug not in slugs:
                slugs.append(row.slug)
    except Exception as exc:  # noqa: BLE001
        # Sem registo de clientes ainda dá para servir a plataforma. Devolver
        # lista vazia aqui parava TUDO por causa de uma consulta.
        logger.warning("por_cada_cliente: não deu para listar clientes: %s", exc)
    return slugs


async def _resolver(slug: str):
    """O contexto deste cliente, resolvido DE DENTRO de um laco a correr.

    **Nao se usa o `_resolve_worker_side`.** Ele faz `asyncio.run(...)`, que
    rebenta com «cannot be called from a running event loop» quando ja ha um
    laco — e a excepcao e engolida por um `except` largo que devolve o
    contexto por omissao.

    Resultado, visto em producao: os tres clientes resolviam todos para
    «default», o `session_for` devolvia a base da PLATAFORMA aos tres, e os
    mesmos 10 agentes corriam TRES VEZES — um por cada volta do ciclo. Custo a
    triplicar, e os agentes dos clientes a nao correr de todo.

    O `_resolve_worker_side` esta certo onde nasceu: e chamado do
    `task_prerun` do Celery, que corre FORA do laco. So nao serve aqui.

    Usa a mesma cache, para a primeira volta pagar a consulta e as seguintes
    nao.
    """
    from src.api.middleware.tenant_resolver import (
        _cache_get,
        _cache_put,
        _load_tenant_from_db,
    )
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    em_cache = _cache_get(slug)
    if em_cache is not None:
        return em_cache
    try:
        ctx = await _load_tenant_from_db(slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning("por_cada_cliente: nao deu para resolver %r: %s", slug, exc)
        return DEFAULT_TENANT_CONTEXT
    if ctx is not None and not ctx.is_default:
        # `_cache_put(ctx)` — o slug vem DE DENTRO do contexto.
        #
        # **Esta linha impediu qualquer agente de correr a horas.** Chamava
        # `_cache_put(slug, ctx)` e a funcao so aceita o contexto:
        #
        #     agent-scheduler[sandbox] falhou: _cache_put() takes 1
        #     positional argument but 2 were given
        #
        # Uma vez por cliente, a cada cinco minutos, desde que o agendador
        # entrou em producao. E o `schedule_agents` apanhava a excepcao por
        # cliente e seguia — devolvendo `agents_scheduled: 0`, que se le
        # como «nao havia nada por correr» e nao como «rebentou em todos».
        #
        # Foi assim que passou despercebido: o beat dizia que despachava, o
        # worker dizia que a tarefa tinha sucesso, e o numero era zero.
        _cache_put(ctx)
        return ctx
    # Um slug que nao resolve NAO pode cair no default em silencio: seria
    # correr os agentes da plataforma a pensar que sao os deste cliente.
    logger.warning(
        "por_cada_cliente: %r nao resolveu para um cliente com base propria "
        "— ignorado nesta passagem",
        slug,
    )
    return None


@asynccontextmanager
async def contexto_do_cliente(slug: str) -> AsyncIterator[None]:
    """Põe o cliente em contexto enquanto o bloco corre.

    O `.delay()` lê o `current_tenant()` para escrever o cabeçalho da
    mensagem — por isso o contexto tem de estar posto enquanto se ENFILEIRA,
    não só enquanto se lê a base.
    """
    from src.core.tenant_context import (
        DEFAULT_TENANT_CONTEXT,
        reset_current_tenant,
        set_current_tenant,
    )

    if slug == DEFAULT_TENANT_CONTEXT.slug:
        ctx = DEFAULT_TENANT_CONTEXT
    else:
        ctx = await _resolver(slug)

    if ctx is None:
        # Nao resolveu. Saltar e melhor do que correr contra a base errada.
        yield False
        return

    token = set_current_tenant(ctx)
    try:
        yield True
    finally:
        reset_current_tenant(token)


async def por_cada_cliente(
    passagem: Callable[[str], Awaitable[Tuple[int, int]]],
    nome: str = "scheduler",
) -> Tuple[int, int]:
    """Corre `passagem(slug)` na base de cada cliente e soma os resultados.

    Um cliente que rebente é registado e ignorado — os outros correm. Uma base
    indisponível é um cliente sem agentes durante cinco minutos; sem esta
    guarda seria toda a gente sem agentes até alguém reparar.
    """
    total_a, total_b = 0, 0
    correram, falharam = 0, 0
    for slug in await clientes_activos():
        try:
            async with contexto_do_cliente(slug) as resolveu:
                if not resolveu:
                    continue
                a, b = await passagem(slug)
            total_a += a
            total_b += b
            correram += 1
            if a or b:
                logger.info("%s[%s]: %s enfileirados, %s corrigidos", nome, slug, a, b)
        except Exception as exc:  # noqa: BLE001
            falharam += 1
            logger.warning("%s[%s] falhou: %s", nome, slug, exc)

    # ── Zero clientes com sucesso NAO e zero agentes por correr. ──────
    #
    # A soma la em cima nao distingue «olhei em todos e nao havia nada» de
    # «nao cheguei a olhar em lado nenhum». Sao a mesma coisa vista de fora:
    # `agents_scheduled: 0`.
    #
    # E foi assim que uma excepcao por cliente — `_cache_put()` chamada com
    # dois argumentos — passou despercebida em producao: o beat dizia que
    # despachava, o worker dizia que a tarefa tinha sucesso, e o numero era
    # zero. Nenhum agente correu a horas, e nada nos registos dizia isso.
    #
    # Um aviso por passagem, so quando falharam TODOS: se um cliente
    # respondeu, a passagem correu, e um alarme por causa de outro seria
    # ruido a cada cinco minutos.
    if falharam and not correram:
        logger.error(
            "%s: nenhum cliente respondeu (%d falharam). Nenhum agente foi "
            "enfileirado — isto nao e uma passagem vazia, e uma passagem "
            "que nao chegou a acontecer.",
            nome,
            falharam,
        )
    return total_a, total_b
