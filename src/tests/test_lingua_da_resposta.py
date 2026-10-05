# -*- coding: utf-8 -*-
"""A língua das respostas pode diferir da da interface.

> «tem pessoas que falam mais idiomas, querem a plataforma de uma forma,
>  e querem a resposta de outra, por causa dos dados» — Lucas, 05/10/2026

O caso concreto que ele deu: uma empresa espanhola cujos dados — tabelas,
nomes de colunas — estão em inglês. É preciso ler o dado em inglês e
responder em castelhano.

Até aqui havia uma preferência só, `language`, a servir a interface e a
IA ao mesmo tempo.

── O que NÃO mudou, e é importante ─────────────────────────────────

A resposta continua a seguir **quem pergunta**, nunca os dados nem o
projecto. Assinalei isso como defeito a 04/10 e estava errado. O que se
acrescenta é poder dizer «a interface em português, as respostas em
castelhano» — não é o dado a decidir.
"""

from __future__ import annotations

import pytest

from src.core.locale import DEFAULT_LOCALE, lingua_da_resposta


def test_sem_escolha_segue_a_interface():
    assert lingua_da_resposta({"language": "pt"}) == "pt"
    assert lingua_da_resposta({"language": "es"}) == "es"


def test_a_escolha_sobrepoe_se_a_interface():
    # O caso do Lucas: plataforma numa língua, respostas noutra.
    assert lingua_da_resposta({"language": "pt", "answer_language": "es"}) == "es"
    assert lingua_da_resposta({"language": "es", "answer_language": "en"}) == "en"


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_vazio_quer_dizer_como_a_interface_e_nao_ingles(vazio):
    """O engano mais fácil de cometer aqui.

    «Como a interface» grava-se como string vazia. Se alguém trocar o
    `or` por um `if is not None`, a string vazia passa a ser uma escolha
    e toda a gente recebe respostas na língua por omissão.
    """
    assert lingua_da_resposta({"language": "es", "answer_language": vazio}) == "es"


def test_sem_preferencias_nenhumas():
    assert lingua_da_resposta({}) == DEFAULT_LOCALE
    assert lingua_da_resposta(None) == DEFAULT_LOCALE


def test_normaliza_o_que_vier():
    # `es-MX` é castelhano; o catálogo só tem `es`.
    assert lingua_da_resposta({"answer_language": "es-MX"}) == "es"
    assert lingua_da_resposta({"language": "pt-BR"}) == "pt"


def test_os_tres_caminhos_da_ia_usam_o_resolvedor():
    """Chat, mensagens e agentes — os três, ou nenhum serve.

    Deixar um a ler `preferences["language"]` directamente dava um
    produto onde a conversa respeita a escolha e o agente não; e a
    pessoa não tem como saber porquê.
    """
    import inspect

    from src.api.v1 import agents, ai

    for modulo in (ai, agents):
        fonte = inspect.getsource(modulo)
        sem_comentarios = "\n".join(l for l in fonte.splitlines() if not l.strip().startswith("#"))
        assert (
            'get("language"' not in sem_comentarios
        ), f"{modulo.__name__} voltou a ler a língua da interface para a IA"
        assert "lingua_da_resposta" in sem_comentarios
