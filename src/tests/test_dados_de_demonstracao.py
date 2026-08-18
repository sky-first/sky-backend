"""Dados de demonstração ligados a partir das Definições.

Substitui um Job de Kubernetes corrido à mão, que exigia acertar três coisas
— o SHA da imagem, o `securityContext` para o Kyverno, e um email de dono que
existisse naquela base — e cada uma delas falhou pelo menos uma vez.

O que estes testes guardam é a decisão que torna isto seguro:

**Quem liga fica dono.** Antes, as ligações ficavam de
`rbac.owner@example.com`, um utilizador de semente. Isso não é um detalhe
cosmético: `DataConnection.created_by` é `ON DELETE CASCADE`, portanto apagar
esse utilizador — coisa que o Lucas pediu, ao querer a plataforma limpa —
levava as ligações atrás. Foi assim que este problema apareceu.

E **desligar apaga só o que ligar criou**. Uma ligação que o cliente tenha
criado com o mesmo nome fica, porque o dono não bate certo.
"""

from __future__ import annotations

import pytest

from src.services import demo_data_service as demo


class _Def:
    """As definições, com e sem base de demonstração configurada."""

    def __init__(self, **kw):
        self.DEMO_PG_HOST = kw.get("host", "")
        self.DEMO_PG_USER = kw.get("user", "")
        self.DEMO_PG_PASSWORD = kw.get("password", "")
        self.DEMO_PG_PORT = kw.get("port", 5432)
        self.DEMO_PG_DB = kw.get("db", "skydemo")
        self.DEMO_PG_SSL_MODE = kw.get("ssl", "require")
        # Precisa de existir porque  passou a decifrar a configuração
        # para ir buscar o esquema de cada ligação.
        self.ENCRYPTION_KEY = kw.get("key", "x" * 32)


def test_sem_credenciais_a_funcionalidade_nao_esta_disponivel(monkeypatch):
    """Um botão que só sabe dar erro é pior do que nenhum.

    Em desenvolvimento local, ou num ambiente onde a base de demonstração não
    existe, o ecrã não deve oferecer isto.
    """
    monkeypatch.setattr(demo, "settings", _Def())
    assert demo.configurada() is False


def test_com_credenciais_fica_disponivel(monkeypatch):
    monkeypatch.setattr(demo, "settings", _Def(host="db.exemplo", user="leitor", password="x"))
    assert demo.configurada() is True


@pytest.mark.parametrize("em_falta", ["host", "user", "password"])
def test_faltando_uma_credencial_nao_chega(monkeypatch, em_falta):
    """As três são precisas. Metade da configuração é pior do que nenhuma:
    o botão aparecia e falhava ao ser tocado."""
    kw = {"host": "db.exemplo", "user": "leitor", "password": "x"}
    kw[em_falta] = ""
    monkeypatch.setattr(demo, "settings", _Def(**kw))
    assert demo.configurada() is False


@pytest.mark.asyncio
async def test_ligar_sem_configuracao_recusa_em_vez_de_rebentar(monkeypatch):
    monkeypatch.setattr(demo, "settings", _Def())
    with pytest.raises(demo.DemoDataIndisponivel):
        await demo.ligar(None, None)


def test_a_configuracao_da_ligacao_leva_o_esquema(monkeypatch):
    """Cada ligação aponta a um esquema diferente — é o que as distingue.

    Todas para a MESMA base: nada é copiado para a base do cliente.
    """
    monkeypatch.setattr(demo, "settings", _Def(host="db.exemplo", user="leitor", password="x"))
    cfg = demo._config("crm")
    assert cfg["schema"] == "crm"
    assert cfg["host"] == "db.exemplo"
    assert cfg["database"] == "skydemo"
    assert cfg["ssl_mode"] == "require"


def test_sao_cinco_e_sao_estas():
    """A lista tem de bater certo com a do `seed_demo_connections.py`.

    Se divergirem, o que o ecrã liga deixa de ser o que o semeador põe — e
    ninguém dá por isso até um cliente perguntar por que razão lhe falta uma.
    """
    nomes = [l["nome"] for l in demo.LIGACOES]
    esquemas = [l["esquema"] for l in demo.LIGACOES]
    assert len(demo.LIGACOES) == 5
    assert "Demo — Sales" in nomes
    assert esquemas == ["crm", "marketing", "finance", "web_analytics", "product_usage"]


def test_o_nome_do_espaco_e_fixo():
    """É por ele que `desligar()` encontra o que apagar. Mudá-lo sem mudar os
    dois lados deixava espaços órfãos que ninguém consegue remover pelo ecrã."""
    assert demo.NOME_DO_ESPACO == "Dados de demonstração"


def test_desligar_filtra_por_dono():
    """A guarda que impede apagar o que não é nosso.

    `_ligacoes_existentes` filtra por `created_by`. Sem isso, desligar os
    dados de demonstração apagava uma ligação que o cliente tivesse criado
    com o mesmo nome — e essa não tem volta.
    """
    import inspect

    fonte = inspect.getsource(demo._ligacoes_existentes)
    assert "created_by" in fonte
    assert "deleted_at" in fonte  # nem toca no que já foi removido


# ── O esquema: sem ele, a demonstração não responde a nada ───────────────────


@pytest.mark.asyncio
async def test_ligar_descobre_as_tabelas_e_liga_as_ao_projeto(db_session, monkeypatch):
    """O buraco encontrado a 18/08/2026 no nosso próprio tenant.

    `ligar()` criava as cinco ligações e o `SpaceConnection`, e ficava por aí.
    Sem metadados e sem `space_tables`, a demonstração aparecia montada — cinco
    ligações, estado "activo" — e não tinha uma única tabela por trás. Em
    produção, no `skyfirstlabs`, esteve assim desde sempre: zero
    `connection_metadata`, zero `space_tables`.

    E como a fronteira de dados passa a ser o projeto, esta é a mesma linha que
    dá dados ao projeto: ligar a demonstração e escolher os dados passam a ser
    o mesmo gesto.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from src.models.connection import ConnectionMetadata
    from src.models.space import SpaceTable
    from src.models.user import User

    monkeypatch.setattr(demo, "settings", _Def(host="db.exemplo", user="leitor", password="x"))

    class _ConnectorFalso:
        async def get_metadata(self, config):
            esquema = config["schema"]
            return {
                "tables": [
                    {"name": f"{esquema}_clientes", "schema": esquema},
                    {"name": f"{esquema}_vendas", "schema": esquema},
                ],
                "schemas": [{"name": esquema}],
            }

    monkeypatch.setattr("src.connectors.registry.get_connector", lambda _cid: _ConnectorFalso())
    monkeypatch.setattr(
        "src.utils.encryption.decrypt_dict",
        lambda cfg, _k: {"schema": cfg.get("schema", "crm")},
    )

    dono = User(
        id=_uuid.uuid4(),
        email="dono@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Dono",
    )
    db_session.add(dono)
    await db_session.flush()

    resultado = await demo.ligar(db_session, dono)

    # Duas tabelas por ligação, cinco ligações.
    assert resultado["tabelas"] == 10

    metadados = (await db_session.execute(select(ConnectionMetadata))).scalars().all()
    assert len(metadados) == 5
    assert all(m.tables for m in metadados), "uma ligação ficou sem esquema"

    tabelas = (await db_session.execute(select(SpaceTable))).scalars().all()
    assert len(tabelas) == 10
    assert {t.schema_name for t in tabelas} == {
        "crm",
        "marketing",
        "finance",
        "web_analytics",
        "product_usage",
    }


@pytest.mark.asyncio
async def test_ligar_duas_vezes_nao_duplica_tabelas(db_session, monkeypatch):
    """`ligar()` é idempotente e isso tem de continuar verdade depois de passar
    a mexer em `space_tables` — senão cada visita às Definições multiplica as
    linhas do projeto."""
    import uuid as _uuid

    from sqlalchemy import select

    from src.models.space import SpaceTable
    from src.models.user import User

    monkeypatch.setattr(demo, "settings", _Def(host="db.exemplo", user="leitor", password="x"))

    class _ConnectorFalso:
        async def get_metadata(self, config):
            return {"tables": [{"name": "t", "schema": config["schema"]}], "schemas": []}

    monkeypatch.setattr("src.connectors.registry.get_connector", lambda _cid: _ConnectorFalso())
    monkeypatch.setattr(
        "src.utils.encryption.decrypt_dict",
        lambda cfg, _k: {"schema": cfg.get("schema", "crm")},
    )

    dono = User(
        id=_uuid.uuid4(),
        email="dono2@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Dono",
    )
    db_session.add(dono)
    await db_session.flush()

    await demo.ligar(db_session, dono)
    segunda = await demo.ligar(db_session, dono)

    assert segunda["tabelas"] == 0  # nada de novo para acrescentar
    tabelas = (await db_session.execute(select(SpaceTable))).scalars().all()
    assert len(tabelas) == 5


@pytest.mark.asyncio
async def test_uma_ligacao_sem_esquema_nao_derruba_as_outras(db_session, monkeypatch):
    """Se o esquema de uma falhar, as outras quatro continuam.

    A alternativa — rebentar tudo — deixava o cliente sem demonstração nenhuma
    por causa de um esquema. Mas fica registado, porque uma demonstração com
    quatro dos cinco responde torto e isso é pior de diagnosticar.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from src.models.space import SpaceTable
    from src.models.user import User

    monkeypatch.setattr(demo, "settings", _Def(host="db.exemplo", user="leitor", password="x"))

    class _ConnectorRabugento:
        async def get_metadata(self, config):
            if config["schema"] == "finance":
                raise RuntimeError("sem rede")
            return {"tables": [{"name": "t", "schema": config["schema"]}], "schemas": []}

    monkeypatch.setattr("src.connectors.registry.get_connector", lambda _cid: _ConnectorRabugento())
    monkeypatch.setattr(
        "src.utils.encryption.decrypt_dict",
        lambda cfg, _k: {"schema": cfg.get("schema", "crm")},
    )

    dono = User(
        id=_uuid.uuid4(),
        email="dono3@empresa-de-mentira.pt",
        role="member",
        password_hash="x",
        name="Dono",
    )
    db_session.add(dono)
    await db_session.flush()

    resultado = await demo.ligar(db_session, dono)

    assert resultado["tabelas"] == 4
    esquemas = {
        t.schema_name for t in (await db_session.execute(select(SpaceTable))).scalars().all()
    }
    assert "finance" not in esquemas
