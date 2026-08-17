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


def test_sem_credenciais_a_funcionalidade_nao_esta_disponivel(monkeypatch):
    """Um botão que só sabe dar erro é pior do que nenhum.

    Em desenvolvimento local, ou num ambiente onde a base de demonstração não
    existe, o ecrã não deve oferecer isto.
    """
    monkeypatch.setattr(demo, "settings", _Def())
    assert demo.configurada() is False


def test_com_credenciais_fica_disponivel(monkeypatch):
    monkeypatch.setattr(
        demo, "settings", _Def(host="db.exemplo", user="leitor", password="x")
    )
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
    monkeypatch.setattr(
        demo, "settings", _Def(host="db.exemplo", user="leitor", password="x")
    )
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
