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
