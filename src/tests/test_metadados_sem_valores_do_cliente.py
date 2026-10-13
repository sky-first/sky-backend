"""Os metadados das ligações não levam valores do cliente.

Princípio (13/10/2026): nunca guardamos dados do cliente. O conector Postgres
escrevia «Possible values: 'a', 'b'» (valores reais, ≤ 20 por coluna) na
descrição das colunas, que ficava em ``connection_metadata`` e seguia para os
embeddings do sky-ai. Estes testes fixam:

* o conector já não lê valores (nenhum ``SELECT DISTINCT``) e a descrição é
  só o comentário da base;
* nenhum conector volta a escrever a pista;
* um ``sync`` não preserva a pista antiga nas descrições guardadas;
* a limpeza das bases tira a pista, é idempotente, e pede nova descoberta
  forçada ao sky-ai por cada espaço.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.metadados_sem_valores import (
    descricao_sem_valores,
    limpar_metadados_da_base,
    pedir_nova_descoberta,
    tabelas_sem_valores,
)

CONECTORES = Path(__file__).resolve().parents[1] / "connectors"


# ── O conector ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conector_postgres_nao_le_valores_das_colunas(monkeypatch):
    import src.connectors.postgresql as pg_mod

    consultas: list[str] = []

    async def fetch(sql, *args):
        consultas.append(sql)
        if "FROM pg_class c" in sql and "pg_attribute" not in sql:
            return [
                {
                    "schema_name": "public",
                    "table_name": "faturas",
                    "description": None,
                    "row_count": 120,  # pequena: era aqui que se amostrava
                }
            ]
        if "pg_attribute" in sql:
            return [
                {
                    "column_name": "estado",
                    "data_type": "text",
                    "is_nullable": True,
                    "description": "Estado da fatura",
                }
            ]
        raise AssertionError(f"consulta inesperada aos dados do cliente: {sql}")

    conn = SimpleNamespace(fetch=fetch, close=AsyncMock(), execute=AsyncMock())

    async def connect(**_kw):
        return conn

    monkeypatch.setattr(pg_mod.asyncpg, "connect", connect)
    meta = await pg_mod.PostgreSQLConnector().get_metadata(
        {"host": "h", "username": "u", "password": "p", "database": "d"}
    )

    col = meta["tables"][0]["columns"][0]
    assert col["description"] == "Estado da fatura"
    assert not any("DISTINCT" in c.upper() for c in consultas)


def test_nenhum_conector_escreve_valores_nas_descricoes():
    culpados = [
        f.name
        for f in CONECTORES.glob("*.py")
        if "Possible values" in f.read_text(encoding="utf-8").replace("«Possible values:", "")
    ]
    assert not culpados, f"pista de valores em: {culpados}"


# ── A pista e a sua remoção ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "antes,depois",
    [
        ("Possible values: 'paid', 'sent'", None),
        ("Estado. Possible values: 'Joana', 'Rui'", "Estado"),
        ("Estado. Possible values: 'a. b', 'c'", "Estado"),
        ("Comentário normal", "Comentário normal"),
        (None, None),
    ],
)
def test_descricao_sem_valores(antes, depois):
    assert descricao_sem_valores(antes) == depois


def test_tabelas_sem_valores_mexe_so_nas_descricoes():
    tabelas = [
        {
            "name": "faturas",
            "description": "Faturas",
            "tags": ["x"],
            "columns": [
                {"name": "estado", "type": "text", "description": "Possible values: 'Joana'"},
                {"name": "id", "type": "int", "description": None},
            ],
        }
    ]
    novas, n = tabelas_sem_valores(tabelas)
    assert n == 1
    assert novas[0]["columns"][0] == {"name": "estado", "type": "text", "description": None}
    assert novas[0]["columns"][1] == tabelas[0]["columns"][1]
    assert novas[0]["tags"] == ["x"]
    assert "Joana" in tabelas[0]["columns"][0]["description"], "não muda o original"


# ── O sync não preserva a pista antiga ────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_nao_preserva_a_pista_guardada(monkeypatch):
    import src.services.connection_service as cs

    cid = uuid.uuid4()
    servico = cs.ConnectionService.__new__(cs.ConnectionService)
    servico.db = SimpleNamespace(commit=AsyncMock(), add=lambda *_: None)
    servico.connection_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                id=cid, connector_id="postgresql", config={}, sync_frequency=None
            )
        ),
        update=AsyncMock(),
    )
    guardado = SimpleNamespace(
        id=uuid.uuid4(),
        tables=[
            {
                "name": "faturas",
                "schema": "public",
                "description": "Faturas. Possible values: 'Joana'",
                "columns": [
                    {"name": "estado", "description": "Editado pelo utilizador"},
                    {"name": "cliente", "description": "Possible values: 'Joana', 'Rui'"},
                ],
            }
        ],
    )
    servico.metadata_repo = SimpleNamespace(
        get_by_connection_id=AsyncMock(return_value=guardado), update=AsyncMock()
    )
    servico.space_repo = SimpleNamespace(get_spaces_by_connection_id=AsyncMock(return_value=[]))
    servico._assert_user_can_access_connection = AsyncMock()

    fresco = {
        "tables": [
            {
                "name": "faturas",
                "schema": "public",
                "description": None,
                "columns": [
                    {"name": "estado", "description": None},
                    {"name": "cliente", "description": "Cliente"},
                ],
            }
        ],
        "schemas": ["public"],
    }
    monkeypatch.setattr(
        cs,
        "get_connector",
        lambda _id: SimpleNamespace(get_metadata=AsyncMock(return_value=fresco)),
    )

    await servico.sync_connection(cid, SimpleNamespace(id=uuid.uuid4()))

    tabelas = servico.metadata_repo.update.await_args.kwargs["tables"]
    assert "Possible values" not in str(tabelas)
    assert tabelas[0]["description"] == "Faturas"
    cols = {c["name"]: c["description"] for c in tabelas[0]["columns"]}
    assert cols["estado"] == "Editado pelo utilizador", "edições continuam preservadas"
    assert cols["cliente"] == "Cliente", "a pista guardada não tapa a descrição nova"


# ── A limpeza das bases ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_limpeza_tira_a_pista_e_e_idempotente(db_session, test_user):
    from sqlalchemy import select

    from src.models.connection import ConnectionMetadata, DataConnection

    ligacao = DataConnection(
        id=uuid.uuid4(),
        name="pg",
        connector_id="postgresql",
        config={"host": "h"},
        created_by=test_user["user"].id,
    )
    limpa = DataConnection(
        id=uuid.uuid4(),
        name="pg2",
        connector_id="postgresql",
        config={"host": "h"},
        created_by=test_user["user"].id,
    )
    db_session.add_all([ligacao, limpa])
    await db_session.flush()
    db_session.add_all(
        [
            ConnectionMetadata(
                connection_id=ligacao.id,
                tables=[
                    {
                        "name": "t",
                        "columns": [{"name": "c", "description": "X. Possible values: 'Joana'"}],
                    }
                ],
                schemas=[],
            ),
            ConnectionMetadata(
                connection_id=limpa.id,
                tables=[{"name": "u", "columns": [{"name": "c", "description": "Y"}]}],
                schemas=[],
            ),
        ]
    )
    await db_session.commit()

    assert await limpar_metadados_da_base(db_session, a_serio=False) == [(ligacao.id, 1)]
    # O dry-run não mexe.
    assert await limpar_metadados_da_base(db_session, a_serio=False) == [(ligacao.id, 1)]

    assert await limpar_metadados_da_base(db_session, a_serio=True) == [(ligacao.id, 1)]
    cm = (
        await db_session.execute(
            select(ConnectionMetadata).where(ConnectionMetadata.connection_id == ligacao.id)
        )
    ).scalar_one()
    await db_session.refresh(cm)
    assert cm.tables[0]["columns"][0]["description"] == "X"

    # Segunda corrida: nada a fazer.
    assert await limpar_metadados_da_base(db_session, a_serio=True) == []


@pytest.mark.asyncio
async def test_nova_descoberta_forcada_por_cada_espaco(monkeypatch):
    import src.repositories.space as space_mod

    com, sem = uuid.uuid4(), uuid.uuid4()
    e1, e2 = SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())

    class _Repo:
        def __init__(self, _db):
            pass

        async def get_spaces_by_connection_id(self, cid):
            return [e1, e2] if cid == com else []

    monkeypatch.setattr(space_mod, "SpaceRepository", _Repo)
    ai = SimpleNamespace(discover_connection=AsyncMock())

    pedidos, sem_espaco = await pedir_nova_descoberta(
        None, [com, sem], ai_client=ai, tenant_slug="sandbox"
    )

    assert pedidos == 2
    assert sem_espaco == [str(sem)]
    for chamada in ai.discover_connection.await_args_list:
        assert chamada.kwargs["skip_if_recent_seconds"] == 0
        assert chamada.kwargs["tenant_slug"] == "sandbox"
        assert chamada.kwargs["connection_id"] == str(com)


@pytest.mark.asyncio
async def test_cliente_http_passa_o_skip_ao_sky_ai(monkeypatch):
    import src.ai.http_client as hc

    enviados = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class _Cliente:
        def __init__(self, **kw):
            enviados["headers"] = kw.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, params=None):
            enviados["params"] = params
            return _Resp()

    monkeypatch.setattr(hc.httpx, "AsyncClient", _Cliente)
    await hc.AIServiceHTTPClient().discover_connection(
        "c", "s", run_in_background=True, tenant_slug="sandbox", skip_if_recent_seconds=0
    )
    assert enviados["params"]["skip_if_recent_seconds"] == 0
    assert enviados["headers"] == {"X-Tenant-Slug": "sandbox"}
