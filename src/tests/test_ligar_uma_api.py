# -*- coding: utf-8 -*-
"""Uma ligação a uma API tem de servir para alguma coisa.

> *"criar uma conexao estilo API, pode ser qualquer API publica... quero fazer
> pergunta com alguma api publica que possa existir por exemplo de
> temperatura"*
> — Lucas, 31/08/2026

---

**O que aconteceu ao experimentar, contra um servidor a sério.**

Criei uma ligação `rest-api` à Open-Meteo (`https://api.open-meteo.com/v1`).

    POST /connections            → 201, status "active"
    POST /connections/{id}/test  → {"success": true, "latency": 1528}
    GET  /connections/{id}/metadata → {"tables": [], "schemas": []}

A ligação existe, passa no teste, e **não devolve nada**. Nada para escolher
no passo do esquema, nada que chegue ao motor — e a pergunta sobre a
temperatura acabaria em «este projeto ainda não tem dados ligados».

**A causa não era o motor.** `RestAPIConnector.get_metadata` lê
`config["endpoints"]` e trata cada um como se fosse uma tabela — porque uma
API não tem esquema para descobrir, e sondá-la às cegas é frágil. Só que o
catálogo nunca declarou esse campo, e por isso nenhum cliente o pedia.

Repeti a criação com um ponto de acesso na configuração:

    "endpoints": [{"name": "previsao", "path": "/forecast", "method": "GET"}]
    GET /connections/{id}/metadata → {"tables": [{"name": "previsao", ...}]}

A peça estava toda lá. Faltava a pergunta.
"""
from __future__ import annotations

import asyncio

from src.connectors.rest_api import RestAPIConnector
from src.services.connector_service import ConnectorService


def _catalogo() -> dict:
    # O serviço pede uma sessão que o catálogo não usa — ele é uma constante
    # em memória. Passar `None` mantém o teste sem base de dados.
    for c in ConnectorService(None).get_connectors():
        if c.id == "rest-api":
            return {f.key: f for f in c.fields}
    raise AssertionError("o conector rest-api desapareceu do catálogo")


class TestOCatalogoPedeOsPontosDeAcesso:
    def test_o_campo_existe(self):
        assert "endpoints" in _catalogo()

    def test_e_nao_e_obrigatorio(self):
        """Uma ligação sem pontos de acesso continua a poder criar-se.

        Obrigar aqui empurrava quem só quer testar a autenticação a
        inventar um caminho. O aviso vive no ecrã, onde se percebe o que
        se perde.
        """
        assert _catalogo()["endpoints"].required is False

    def test_e_diz_para_que_serve(self):
        d = (_catalogo()["endpoints"].description or "").lower()
        assert "table" in d


class TestSemPontosDeAcessoNaoHaTabelas:
    """O caso que se viu: ligação boa, esquema vazio."""

    def test_config_sem_endpoints_devolve_zero_tabelas(self):
        meta = asyncio.run(
            RestAPIConnector().get_metadata({"base_url": "https://api.open-meteo.com/v1"})
        )
        assert meta["tables"] == []

    def test_uma_lista_vazia_tambem(self):
        meta = asyncio.run(
            RestAPIConnector().get_metadata(
                {"base_url": "https://api.open-meteo.com/v1", "endpoints": []}
            )
        )
        assert meta["tables"] == []


class TestComPontosDeAcessoHaTabelas:
    def test_cada_um_vira_uma_tabela(self):
        meta = asyncio.run(
            RestAPIConnector().get_metadata(
                {
                    "base_url": "https://api.open-meteo.com/v1",
                    "endpoints": [
                        {
                            "name": "previsao",
                            "path": "/forecast",
                            "method": "GET",
                            "description": "Previsão por latitude e longitude",
                        }
                    ],
                }
            )
        )
        assert [t["name"] for t in meta["tables"]] == ["previsao"]

    def test_e_leva_o_caminho_e_o_metodo_consigo(self):
        """Sem isto o motor sabe o nome e não sabe o que pedir."""
        meta = asyncio.run(
            RestAPIConnector().get_metadata(
                {
                    "base_url": "https://x",
                    "endpoints": [{"name": "p", "path": "/forecast", "method": "get"}],
                }
            )
        )
        m = meta["tables"][0]["metadata"]
        assert m["path"] == "/forecast"
        assert m["method"] == "GET", "o método é normalizado para maiúsculas"

    def test_a_descricao_sobrevive(self):
        """É por ela que o motor escolhe este ponto de acesso e não outro."""
        meta = asyncio.run(
            RestAPIConnector().get_metadata(
                {
                    "base_url": "https://x",
                    "endpoints": [{"name": "p", "path": "/a", "description": "temperatura"}],
                }
            )
        )
        assert meta["tables"][0]["metadata"]["description"] == "temperatura"

    def test_um_ponto_de_acesso_sem_nome_nao_fica_sem_nome(self):
        """Cai para o caminho. Uma linha sem nome na lista não se toca."""
        meta = asyncio.run(
            RestAPIConnector().get_metadata(
                {"base_url": "https://x", "endpoints": [{"path": "/forecast"}]}
            )
        )
        assert meta["tables"][0]["name"] == "/forecast"
