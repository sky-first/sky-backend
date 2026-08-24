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
        from src.workers.tenant_context_propagation import _resolve_worker_side

        ctx = _resolve_worker_side(slug)

    token = set_current_tenant(ctx)
    try:
        yield
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
    for slug in await clientes_activos():
        try:
            async with contexto_do_cliente(slug):
                a, b = await passagem(slug)
            total_a += a
            total_b += b
            if a or b:
                logger.info("%s[%s]: %s enfileirados, %s corrigidos", nome, slug, a, b)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s[%s] falhou: %s", nome, slug, exc)
    return total_a, total_b
