"""Apagar uma ligação numa base que não tem as tabelas do sky-ai.

Encontrado em produção, a limpar ligações de teste no cliente `sandbox`:

    DELETE /api/v1/connections/{id} -> 500
    UndefinedTableError: relation "embeddings" does not exist

A limpeza do `delete_connection` apaga `embeddings` e `table_metadata` antes
da ligação, porque as chaves estrangeiras são `ON DELETE NO ACTION`. Só que
essas duas tabelas são criadas pelas migrações do **sky-ai**, e as bases dos
clientes no Modelo B só recebem as do **sky-be**. Existem na base da
plataforma; não existem em `tenant_sandbox` nem em `tenant_skyfirstlabs`.

Ou seja: **nenhum cliente conseguia apagar uma ligação de dados.** Não é um
caso de canto — é a operação normal, partida para toda a gente, escondida
atrás de um 500 genérico.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.connection_service import ConnectionService


def _sessao(tabelas_existentes: set[str]) -> MagicMock:
    """Sessão que responde ao `to_regclass` como uma base sem as tabelas do AI."""
    db = MagicMock()
    executados: list[str] = []

    async def execute(clause, params=None):
        sql = str(clause)
        executados.append(sql)
        r = MagicMock()
        if "to_regclass" in sql:
            nome = (params or {}).get("t")
            r.scalar.return_value = nome if nome in tabelas_existentes else None
        else:
            r.scalar.return_value = None
        return r

    db.execute = AsyncMock(side_effect=execute)
    db.executados = executados
    return db


@pytest.mark.asyncio
async def test_nao_apaga_embeddings_quando_a_tabela_nao_existe():
    svc = ConnectionService.__new__(ConnectionService)
    svc.db = _sessao(tabelas_existentes=set())

    await svc._apagar_se_a_tabela_existir(
        "embeddings", "DELETE FROM embeddings WHERE 1=1", {}
    )

    apagou = [s for s in svc.db.executados if s.startswith("DELETE FROM embeddings")]
    assert apagou == [], "não pode correr o DELETE numa base onde a tabela não existe"


@pytest.mark.asyncio
async def test_apaga_normalmente_quando_a_tabela_existe():
    """A outra metade — senão o remédio era deixar de limpar em lado nenhum,
    e ficavam embeddings órfãos na base da plataforma."""
    svc = ConnectionService.__new__(ConnectionService)
    svc.db = _sessao(tabelas_existentes={"embeddings"})

    await svc._apagar_se_a_tabela_existir(
        "embeddings", "DELETE FROM embeddings WHERE 1=1", {}
    )

    apagou = [s for s in svc.db.executados if s.startswith("DELETE FROM embeddings")]
    assert len(apagou) == 1, "onde a tabela existe, a limpeza tem de continuar a correr"


@pytest.mark.asyncio
async def test_nenhuma_limpeza_crua_escapa_ao_guarda():
    """Numa base sem *nenhuma* das tabelas, o delete tem de chegar ao fim.

    A primeira correcção protegeu só `embeddings` e `table_metadata` — as duas
    que apareceram no traceback. Foi promovida, e o `DELETE` voltou a dar 500
    em produção na tabela seguinte:

        UndefinedTableError: relation "pipeline_jobs" does not exist

    Perseguir tabela a tabela é perseguir sintomas. Este teste lê o ficheiro e
    exige que nenhuma limpeza crua fique fora do guarda, para que a próxima
    que alguém acrescentar não repita o mesmo caminho.
    """
    from pathlib import Path

    fonte = Path("src/services/connection_service.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("HARD Deleting connection") :]
    corpo = corpo[: corpo.index("async def test_connection")]

    cruas = [
        linha.strip()
        for linha in corpo.splitlines()
        if 'text("DELETE FROM' in linha
    ]
    assert cruas == [], (
        "estas limpezas não passam pelo `_apagar_se_a_tabela_existir` e vão "
        f"rebentar numa base de cliente: {cruas}"
    )
