# -*- coding: utf-8 -*-
"""Tira as linhas do cliente que ficaram gravadas antes de 13/10/2026.

── Porquê ──────────────────────────────────────────────────────────

> «Nunca guardamos as linhas do cliente.» — Lucas, 13/10/2026

O código deixou de as gravar (os modelos tiram-nas antes de chegarem à
base — ver `src/services/dados_ao_vivo.py`). Mas o que já lá estava
continua lá: as fontes das respostas, os widgets, os achados e as corridas
dos agentes gravados até hoje. Isto limpa o chão.

── O que faz, tabela a tabela ──────────────────────────────────────

* `ai_queries.data_sample` → NULL (a fonte volta a correr o SQL);
* `widgets.data` → sem as listas de linhas, o `value` do KPI e o
  `chart_block.data`; **os de demonstração ficam** (marca `demo`, ou
  `source` = `demo_sectorial`): são dados sintéticos nossos;
* `agent_findings.rows` → só a definição (colunas, SQL, ligação, quantas);
  `agent_findings.series` → `[]`; os de demonstração (`rows.demo`) ficam;
* `agent_executions.result_payload` → só `row_count`/`columns`/`data_bytes`.

A transformação é a MESMA função que os modelos usam na escrita — uma
regra, um sítio.

── Conta primeiro. Sempre. ─────────────────────────────────────────

Sem `--aplicar` **não escreve nada**: mostra, por cliente e por tabela,
quantas linhas mudariam. Só números — nunca o conteúdo, que é exactamente
o que se está a tirar. Correr duas vezes é seguro: a segunda já não
encontra nada para mudar.

    python -I scripts/limpar_linhas_do_cliente.py              # contar
    python -I scripts/limpar_linhas_do_cliente.py --aplicar    # limpar
    python -I scripts/limpar_linhas_do_cliente.py --slug x     # um só

Vai a TODOS os clientes do registo, um a um (cada um tem a sua base —
Modelo B), e à base da plataforma.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

#: Widgets semeados pelas demonstrações sectoriais (antes da marca `demo`).
FONTES_DEMO = ("demo_sectorial", "demo")


def _ler_json(valor: Any) -> Any:
    if isinstance(valor, (str, bytes)):
        try:
            return json.loads(valor)
        except Exception:
            return valor
    return valor


def _cast(conn, tipo: str) -> str:
    """`CAST(:v AS json)` no Postgres; texto simples no SQLite (dos testes)."""
    return f"CAST(:v AS {tipo})" if conn.dialect.name == "postgresql" else ":v"


def _widget(linha) -> Optional[Any]:
    from src.services.dados_ao_vivo import e_demo, widget_sem_linhas

    data = _ler_json(linha.data)
    if (linha.source or "") in FONTES_DEMO or e_demo(data):
        return None
    novo = widget_sem_linhas(linha.type, data)
    return novo if novo != data else None


def _achado_rows(linha) -> Optional[Any]:
    from src.services.dados_ao_vivo import achado_rows_sem_dados

    rows = _ler_json(linha.rows)
    novo = achado_rows_sem_dados(rows)
    return novo if novo != rows else None


def _achado_series(linha) -> Optional[Any]:
    series = _ler_json(linha.series)
    return [] if isinstance(series, list) and series else None


def _execucao(linha) -> Optional[Any]:
    from src.services.dados_ao_vivo import execucao_sem_linhas

    payload = _ler_json(linha.result_payload)
    novo = execucao_sem_linhas(payload)
    return novo if novo != payload else None


#: (nome no relatório, SELECT, coluna, tipo no Postgres, transformação)
PASSOS: List[Tuple[str, str, str, str, Callable[[Any], Optional[Any]]]] = [
    (
        "widgets.data",
        "SELECT id, type, source, data FROM widgets WHERE data IS NOT NULL",
        "data",
        "json",
        _widget,
    ),
    (
        "agent_findings.rows",
        "SELECT id, rows FROM agent_findings WHERE rows IS NOT NULL",
        "rows",
        "jsonb",
        _achado_rows,
    ),
    (
        "agent_findings.series",
        "SELECT id, series FROM agent_findings WHERE series IS NOT NULL",
        "series",
        "jsonb",
        _achado_series,
    ),
    (
        "agent_executions.result_payload",
        "SELECT id, result_payload FROM agent_executions WHERE result_payload IS NOT NULL",
        "result_payload",
        "jsonb",
        _execucao,
    ),
]

_TABELA = {
    "widgets.data": "widgets",
    "agent_findings.rows": "agent_findings",
    "agent_findings.series": "agent_findings",
    "agent_executions.result_payload": "agent_executions",
}


async def limpar_uma_base(conn, aplicar: bool) -> Dict[str, int]:
    """Quantas linhas mudam em cada tabela; com `aplicar`, muda-as.

    `conn` é uma `AsyncConnection` (ou o que `AsyncSession.connection()`
    devolve). Não faz commit: quem chama decide.
    """
    contagens: Dict[str, int] = {}

    # ai_queries: tudo o que tenha linhas passa a NULL.
    linhas = (
        await conn.execute(
            text("SELECT id, data_sample FROM ai_queries WHERE data_sample IS NOT NULL")
        )
    ).fetchall()
    com_linhas = [r.id for r in linhas if _ler_json(r.data_sample) not in (None, [], {})]
    contagens["ai_queries.data_sample"] = len(com_linhas)
    if aplicar:
        for rid in com_linhas:
            await conn.execute(
                text("UPDATE ai_queries SET data_sample = NULL WHERE id = :id"), {"id": rid}
            )

    for nome, consulta, coluna, tipo, transformar in PASSOS:
        mudar: List[Tuple[Any, Any]] = []
        for linha in (await conn.execute(text(consulta))).fetchall():
            novo = transformar(linha)
            if novo is not None:
                mudar.append((linha.id, novo))
        contagens[nome] = len(mudar)
        if aplicar:
            for rid, novo in mudar:
                await conn.execute(
                    text(
                        f"UPDATE {_TABELA[nome]} SET {coluna} = {_cast(conn, tipo)} WHERE id = :id"
                    ),
                    {"v": json.dumps(novo, default=str), "id": rid},
                )
    return contagens


async def _clientes(slug: Optional[str]) -> List[Tuple[str, str]]:
    """(slug, url) de cada cliente activo com base dedicada — e a plataforma.

    A mesma leitura do `migrate_tenants.py` e do `varrer_o_lixo_dos_agentes.py`.
    """
    import os

    from sqlalchemy import select

    from src.config.database import AsyncSessionLocal
    from src.models.tenant import Tenant

    sys.path.insert(0, str(Path(__file__).parent))
    from _ligacao_ao_tenant import url_a_partir_do_registo  # type: ignore

    async with AsyncSessionLocal() as db:
        consulta = select(Tenant).where(Tenant.is_active.is_(True))
        if slug:
            consulta = consulta.where(Tenant.slug == slug)
        registos = list((await db.execute(consulta)).scalars().all())

    plataforma = (os.environ.get("DATABASE_URL") or "").rsplit("/", 1)[-1].split("?")[0]
    saida: List[Tuple[str, str]] = []
    if plataforma and not slug:
        saida.append(("(plataforma)", os.environ["DATABASE_URL"]))
    for row in registos:
        if not row.db_host or not row.db_name or row.db_name == plataforma:
            continue
        saida.append((row.slug, url_a_partir_do_registo(row)))
    return saida


async def principal(aplicar: bool, slug: Optional[str]) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    totais: Dict[str, int] = {}
    falhas = 0
    for nome, url in await _clientes(slug):
        motor = create_async_engine(url, pool_pre_ping=True)
        try:
            async with motor.begin() as conn:
                contagens = await limpar_uma_base(conn, aplicar)
            print(f"=== {nome}")
            for tabela, n in contagens.items():
                totais[tabela] = totais.get(tabela, 0) + n
                print(f"    {tabela:<34} {n:>7}")
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            print(f"=== {nome}: NAO consegui ler ({type(exc).__name__})")
        finally:
            await motor.dispose()

    print("")
    print("TOTAL" + (" (aplicado)" if aplicar else " (só contado)"))
    for tabela, n in totais.items():
        print(f"    {tabela:<34} {n:>7}")
    if not aplicar:
        print("Nada foi alterado. Para limpar: --aplicar")
    return 1 if falhas else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--aplicar", action="store_true", help="escreve (sem isto só conta)")
    p.add_argument("--slug", default=None, help="só este cliente")
    a = p.parse_args()
    sys.exit(asyncio.run(principal(a.aplicar, a.slug)))
