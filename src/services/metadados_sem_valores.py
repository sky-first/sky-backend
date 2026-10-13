"""Os metadados de uma ligação não levam valores do cliente.

Até 13/10/2026 o conector Postgres escrevia na descrição de cada coluna de
texto categórica «Possible values: 'a', 'b', …» — valores reais da base do
cliente, guardados para sempre em ``connection_metadata.tables`` e copiados
pelo sky-ai para ``table_metadata`` e embeddings.

O conector deixou de o fazer. Isto trata do que já lá estava:

* ``sync_connection`` preserva as descrições guardadas (para não perder as
  edições do utilizador) — e por isso preservaria também a pista antiga para
  sempre. ``descricao_sem_valores`` tira-a antes de preservar.
* ``scripts/limpar_valores_das_colunas.py`` limpa ``connection_metadata`` em
  todas as bases (plataforma e clientes) e pede nova descoberta ao sky-ai.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

MARCA_DOS_VALORES = "Possible values:"

# A pista vinha sempre no FIM da descrição: "<comentário>. Possible values: …".
_PISTA = re.compile(r"\.?\s*Possible values:.*\Z", re.S)


def descricao_sem_valores(descricao: Optional[str]) -> Optional[str]:
    """Tira a pista de valores; uma descrição que fique vazia passa a ``None``."""
    if not descricao or MARCA_DOS_VALORES not in descricao:
        return descricao
    limpa = _PISTA.sub("", descricao).strip()
    return limpa or None


def tabelas_sem_valores(tabelas: Any) -> Tuple[List[Any], int]:
    """Cópia de ``connection_metadata.tables`` sem pistas; e quantas tirou.

    Olha para a descrição da tabela e de cada coluna. Tudo o resto fica igual.
    """
    if not isinstance(tabelas, list):
        return tabelas, 0
    tiradas = 0
    saida: List[Any] = []
    for tabela in tabelas:
        if not isinstance(tabela, dict):
            saida.append(tabela)
            continue
        nova = dict(tabela)
        d = nova.get("description")
        if isinstance(d, str) and MARCA_DOS_VALORES in d:
            nova["description"] = descricao_sem_valores(d)
            tiradas += 1
        colunas = nova.get("columns")
        if isinstance(colunas, list):
            novas_colunas = []
            for col in colunas:
                if isinstance(col, dict):
                    cd = col.get("description")
                    if isinstance(cd, str) and MARCA_DOS_VALORES in cd:
                        col = {**col, "description": descricao_sem_valores(cd)}
                        tiradas += 1
                novas_colunas.append(col)
            nova["columns"] = novas_colunas
        saida.append(nova)
    return saida, tiradas


async def limpar_metadados_da_base(db: Any, *, a_serio: bool) -> List[Tuple[Any, int]]:
    """Tira as pistas de ``connection_metadata.tables`` numa base.

    Devolve ``[(connection_id, pistas_tiradas)]`` das ligações afectadas.
    Idempotente: numa segunda corrida a lista vem vazia.
    """
    from sqlalchemy import Text, cast, select

    from src.models.connection import ConnectionMetadata

    linhas = (
        (
            await db.execute(
                select(ConnectionMetadata).where(
                    cast(ConnectionMetadata.tables, Text).like(f"%{MARCA_DOS_VALORES}%")
                )
            )
        )
        .scalars()
        .all()
    )
    afectadas: List[Tuple[Any, int]] = []
    for cm in linhas:
        novas, n = tabelas_sem_valores(cm.tables)
        if not n:
            continue
        afectadas.append((cm.connection_id, n))
        if a_serio:
            cm.tables = novas
    if a_serio and afectadas:
        await db.commit()
    return afectadas


async def pedir_nova_descoberta(
    db: Any,
    connection_ids: List[Any],
    *,
    ai_client: Any,
    tenant_slug: Optional[str],
) -> Tuple[int, List[str]]:
    """Pede ao sky-ai que volte a descobrir cada ligação, por cada espaço.

    O sky-ai lê ``connection_metadata`` (já limpa) e refaz ``table_metadata`` e
    os embeddings — que foram calculados COM os valores. Força a descoberta
    (``skip_if_recent_seconds=0``): os metadados acabaram de mudar.

    Devolve (pedidos feitos, ligações sem espaço). Uma ligação sem espaço não
    tem descoberta a pedir; o script do sky-ai limpa o que lá ficou.
    """
    from src.repositories.space import SpaceRepository

    repo = SpaceRepository(db)
    pedidos = 0
    sem_espaco: List[str] = []
    for cid in connection_ids:
        espacos = await repo.get_spaces_by_connection_id(cid)
        if not espacos:
            sem_espaco.append(str(cid))
            continue
        for espaco in espacos:
            await ai_client.discover_connection(
                connection_id=str(cid),
                space_id=str(espaco.id),
                run_in_background=True,
                tenant_slug=tenant_slug,
                skip_if_recent_seconds=0,
            )
            pedidos += 1
    return pedidos, sem_espaco
