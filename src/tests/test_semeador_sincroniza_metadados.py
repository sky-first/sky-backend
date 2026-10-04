# -*- coding: utf-8 -*-
"""O semeador sectorial tem de sincronizar os metadados das ligações.

── O que o Lucas viu ───────────────────────────────────────────────

Os três projectos sectoriais abriram em produção com as quatro páginas
cheias e os números certos. Ao perguntar na conversa:

    Sky: The AI service rejected the request. Please retry or open a ticket.

── Porque é que os painéis funcionavam e a conversa não ────────────

São dois caminhos diferentes. Os widgets nascem **preenchidos**: o
semeador corre o SQL e grava o resultado, por isso um projecto sem
metadados abre bonito. A conversa e os agentes são **ao vivo** e passam
pelo `sky-ai`, que responde `404` ao `/connections/<id>/query` quando não
encontra metadados para a ligação.

E o backend traduz esse 404 — que não é 400, nem 429, nem 5xx — em «The
AI service rejected the request», uma frase que manda procurar um
defeito no serviço de IA que está bom.

Nos registos do `sky-ai`, a cadeia completa:

    discover_auto_embed_success  embeddings_created: 0, metadata_inserted: 0
    load_agent_config_metadata_query  num_rows_found: 0
    load_agent_config_no_metadata
    POST /connections/<id>/query → 404 Not Found

── Porque é que nenhum teste viu ───────────────────────────────────

Os 41 testes do semeador verificam a geometria, os payloads dos widgets
e o confinamento dos agentes — tudo o que se pode verificar sem base de
dados. O passo que faltava não está no conteúdo: está na **sequência**,
e só se nota com um `sky-ai` do outro lado.

O `seed_demo_connections.py` já fazia isto, com o aviso escrito por
cima:

    # Run metadata discovery on each connection — without this the AI
    # service rejects every chat / agent run with
    # "404 No metadata found for this connection".

O meu semeador não copiou o passo. O aviso estava escrito e eu não o li.

── O que este teste fixa ───────────────────────────────────────────

A sequência, não a implementação: que os identificadores das ligações
saem do semeador e entram na sincronização, e que num ensaio não entram
— porque aí as ligações foram desfeitas e não há nada que
introspeccionar.
"""

from __future__ import annotations

import argparse

import pytest


def _args(aplicar: bool) -> argparse.Namespace:
    return argparse.Namespace(
        sector="restauracion",
        dono=None,
        confirmar_base="tenant_prova",
        aplicar=aplicar,
    )


@pytest.fixture
def cli(monkeypatch):
    """Importa o CLI com o ambiente mínimo que ele exige.

    O módulo recusa-se a carregar sem `DATABASE_URL` — de propósito, para
    não correr contra a base errada por omissão.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/tenant_prova")
    import importlib

    return importlib.import_module("scripts.semear_demo_sectorial")


class _SessaoFalsa:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


IDS = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]


def _montar(cli, monkeypatch, sessao):
    """Substitui tudo o que fala com o mundo e devolve o que foi chamado."""
    chamadas: dict = {}

    async def _sessao_falsa():
        return sessao, "postgresql+asyncpg://u:p@h/tenant_prova"

    async def _semear_falso(db, sector, email_do_dono=None):
        return {
            "ligacoes_criadas": list(IDS),
            "espaco_id": "e",
            "ligacoes": 3,
            "paginas": 4,
            "widgets": 24,
            "agentes": 5,
            "perguntas": 5,
        }

    async def _sincronizar_falso(ids, email=None):
        chamadas["ids"] = list(ids)
        return len(ids)

    monkeypatch.setattr(cli, "_sessao", _sessao_falsa)
    monkeypatch.setattr(cli, "semear", _semear_falso)
    monkeypatch.setattr(cli, "sincronizar_metadados", _sincronizar_falso)
    return chamadas


@pytest.mark.asyncio
async def test_com_aplicar_sincroniza_as_ligacoes_criadas(cli, monkeypatch, capsys):
    sessao = _SessaoFalsa()
    chamadas = _montar(cli, monkeypatch, sessao)

    assert await cli.principal(_args(aplicar=True)) == 0

    assert chamadas.get("ids") == IDS, (
        "as ligações criadas têm de chegar à sincronização — sem isto o "
        "projecto abre com os painéis cheios e a conversa recusa tudo"
    )
    assert sessao.commits == 1
    assert "2/2" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_no_ensaio_nao_sincroniza_nada(cli, monkeypatch):
    # O contrapeso. Sincronizar num ensaio introspeccionaria ligações que
    # acabaram de ser desfeitas pelo rollback — e o erro apareceria como
    # «ligação não existe», longe da causa.
    sessao = _SessaoFalsa()
    chamadas = _montar(cli, monkeypatch, sessao)

    assert await cli.principal(_args(aplicar=False)) == 0

    assert "ids" not in chamadas
    assert sessao.rollbacks == 1


@pytest.mark.asyncio
async def test_o_resumo_nao_mostra_a_lista_crua_de_identificadores(cli, monkeypatch, capsys):
    # `ligacoes_criadas` é um detalhe de passagem entre o motor e a
    # sincronização. Imprimir três UUID no resumo empurra para baixo as
    # linhas que alguém lê de facto.
    sessao = _SessaoFalsa()
    _montar(cli, monkeypatch, sessao)
    await cli.principal(_args(aplicar=True))
    saida = capsys.readouterr().out
    assert "ligacoes_criadas" not in saida
    assert "metadados" in saida


def test_o_motor_devolve_as_ligacoes_criadas():
    """Sem esta chave o CLI sincroniza uma lista vazia e diz `0/0`.

    E `0/0` lê-se como «não havia nada para fazer», não como «o passo
    não recebeu nada» — que é o modo de falhar mais caro que há.
    """
    import inspect

    from scripts.demo_sectorial import motor

    fonte = inspect.getsource(motor.semear)
    assert '"ligacoes_criadas"' in fonte


def test_sincronizar_sem_ligacoes_nao_toca_na_base():
    import asyncio

    from scripts.demo_sectorial.motor import sincronizar_metadados

    assert asyncio.run(sincronizar_metadados([])) == 0
