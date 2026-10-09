# -*- coding: utf-8 -*-
"""Conta — e só depois apaga — as mensagens «não há nada a assinalar».

── Porque é que elas existem aos montes ────────────────────────────

Dois defeitos do `agent_worker`, os dois vindos do MESMO `return`
(corrigidos no #724): o fio dizia «Olhei agora e não há nada a assinalar»
enquanto a execução ficava `failed`, e o `next_execution_at` nunca era
tocado, por isso o Beat reenfileirava o agente de 5 em 5 minutos. Medido
em produção: **111 corridas por agente em 9 horas**, em seis agentes.

O resultado é o que o Lucas viu no telemóvel: a mesma frase repetida até
encher o fio, numa altura em que o agente nem sequer tinha conseguido
correr. A frase era mentira e o volume era um defeito de agendamento.

O #724 fecha a torneira. Isto limpa o chão.

── Conta primeiro. Sempre. ─────────────────────────────────────────

Sem `--apagar` **não escreve nada**: mostra quantas são, por cliente e
por agente, e as datas. É para se poder olhar antes de decidir, porque
isto é uma escrita em produção e não se desfaz.

    python -I scripts/varrer_o_lixo_dos_agentes.py
    python -I scripts/varrer_o_lixo_dos_agentes.py --apagar

Vai a TODOS os clientes do registo, um a um, porque cada um tem a sua
base (Modelo B) e o lixo está em todas elas.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

sys.path.insert(0, ".")

CHAVE = "agent_nothing_to_report"

#: Como se reconhece a frase.
#:
#: **Pela marca E pelo texto, e nao so pela marca.** A `chave_de_texto` e
#: recente (entrou com a traducao das mensagens dos agentes); tudo o que o
#: worker escreveu antes disso tem a frase cravada e a marca a NULL.
#:
#: Medido em producao a 09/10/2026: so pela marca apareciam **1** mensagem;
#: pelo texto apareciam **6288**, das quais 949 num unico fio. Procurar so
#: pela marca teria dado a limpeza por feita com o chao na mesma.
#:
#: As tres linguas, porque o mesmo agente e lido em pt, en e es.
LIXO = """(m.content ILIKE '%nada a assinalar%'
        OR m.content ILIKE '%nothing to flag%'
        OR m.content ILIKE '%nada que se' || chr(241) || 'alar%'
        OR m.chave_de_texto = :chave)"""

CONTAR = text(
    "SELECT c.title AS titulo, COUNT(*) AS quantas,"
    " MIN(m.created_at) AS primeira, MAX(m.created_at) AS ultima"
    " FROM messages m JOIN conversations c ON c.id = m.conversation_id"
    " WHERE " + LIXO + " GROUP BY c.title ORDER BY quantas DESC"
)

#: Fica a MAIS RECENTE de cada fio. Apagar todas deixava o fio vazio e sem
#: explicacao para quem la fosse; ficando uma, quem abrir percebe o que o
#: agente andou a fazer. E a diferenca entre limpar e esconder.
_SEM_O_PREFIXO = LIXO.replace("m.content", "content").replace("m.chave_de_texto", "chave_de_texto")
APAGAR = text(
    "DELETE FROM messages WHERE " + _SEM_O_PREFIXO + " AND id NOT IN ("
    " SELECT DISTINCT ON (conversation_id) id FROM messages"
    " WHERE " + _SEM_O_PREFIXO + " ORDER BY conversation_id, created_at DESC)"
)


async def _clientes() -> list:
    """(slug, url) de cada cliente activo com base dedicada.

    A mesma leitura do `migrate_tenants.py`, e pela mesma razao: cada
    cliente tem a sua base (Modelo B), e o lixo esta em todas elas. A
    base da PLATAFORMA tambem entra — o `sky` do registo aponta para ela
    e la tambem correram agentes antes da Fase 5.
    """
    import os

    from sqlalchemy import select

    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    sys.path.insert(0, "scripts")
    from _ligacao_ao_tenant import url_a_partir_do_registo  # type: ignore

    async with AsyncSessionLocal() as db:
        linhas = list(
            (await db.execute(select(Tenant).where(Tenant.is_active.is_(True)))).scalars().all()
        )

    plataforma = (os.environ.get("DATABASE_URL") or "").rsplit("/", 1)[-1].split("?")[0]
    saida = [("(plataforma)", os.environ["DATABASE_URL"])] if plataforma else []
    for row in linhas:
        if not row.db_host or not row.db_name or row.db_name == plataforma:
            continue
        saida.append((row.slug, url_a_partir_do_registo(row)))
    return saida


async def principal(apagar: bool) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    total = 0
    for slug, url in await _clientes():
        motor = create_async_engine(url, pool_pre_ping=True)
        try:
            async with motor.begin() as db:
                linhas = (await db.execute(CONTAR, {"chave": CHAVE})).fetchall()
                if not linhas:
                    continue
                soma = sum(r.quantas for r in linhas)
                total += soma
                print("")
                print("=== %s — %d mensagens em %d fios" % (slug, soma, len(linhas)))
                for r in linhas:
                    print(
                        "    %4d  %-40s  %s -> %s"
                        % (r.quantas, (r.title or "sem titulo")[:40], r.primeira, r.ultima)
                    )
                if apagar:
                    res = await db.execute(APAGAR, {"chave": CHAVE})
                    print("    apagadas %d (fica a mais recente de cada fio)" % res.rowcount)
        except Exception as exc:
            print("=== %s: NAO consegui ler (%s: %s)" % (slug, type(exc).__name__, exc))
        finally:
            await motor.dispose()

    print("")
    print("TOTAL: %d mensagens «nada a assinalar»" % total)
    if not apagar:
        print("Nada foi apagado. Para apagar: --apagar")


if __name__ == "__main__":
    asyncio.run(principal("--apagar" in sys.argv))
