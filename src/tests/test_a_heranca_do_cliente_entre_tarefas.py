# -*- coding: utf-8 -*-
"""Quando é que uma tarefa sabe de que cliente é.

── Porque isto é um teste e não um comentário ──────────────────────

Porque eu próprio errei a resposta. Escrevi, num documento de desenho,
que «uma task que nasce fora do pedido não herda o contexto». Está
errado — herda, e as netas também. O risco verdadeiro é outro, e é mais
estreito e mais traiçoeiro: é de ORDEM.

E há uma segunda razão, mais forte: **isto é comportamento do
interpretador** (PEP 567), e o backend acabou de saltar de Python 3.11
para 3.12 por causa do SDK do Nova Sonic. Uma mudança de versão é
exactamente o que pode alterar isto sem ninguém notar — e a maneira de
notar é esta.

── O que está em jogo ──────────────────────────────────────────────

O `_current_tenant` tem `default=DEFAULT_TENANT_CONTEXT`, portanto
`current_tenant()` devolve a base da **PLATAFORMA** quando ninguém pôs
nada. Sem excepção, sem aviso, sem uma linha nos registos.

Uma tarefa criada uma linha antes do `set_current_tenant` fica presa a
esse `default` para toda a vida. Se for uma tarefa de vida longa — o
ciclo de escuta de uma sessão de voz, por exemplo — a sessão inteira
consulta a base errada e responde com dados de outro cliente, ou com
nada.

É assim que este defeito voltou sete vezes: em
`core/ingestion/service.py`, no `worker/scan_tasks.py`, nos agentes, no
mapa semântico, nas descobertas e na própria voz. Nunca com um erro.

── A conclusão que se tira daqui ───────────────────────────────────

Não «põe o `set_current_tenant` no sítio certo» — isso é pedir que uma
ordem esteja correcta para sempre. É **passar o contexto por
ARGUMENTO** a quem faz trabalho de cliente, e usar a variável de
contexto só como reforço para os serviços a jusante.

O `voice.py` já faz assim: o `_voice_answer` recebe `ctx`. Ver
`test_a_sessao_global_so_em_sitios_declarados.py`, que guarda a outra
metade do problema — quem abre a sessão global.
"""
from __future__ import annotations

import asyncio
import inspect
from uuid import uuid4

import pytest

from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)

UM_CLIENTE = TenantContext(
    slug="cliente-de-teste", id=uuid4(), tier="pro", display_name="Cliente"
)


async def _de_quem_sou() -> str:
    # Um `sleep` de propósito: sem ele a tarefa podia correr antes de o
    # contexto mudar e o teste passava por acidente de escalonamento.
    await asyncio.sleep(0.01)
    return current_tenant().slug


class TestAOrdemEOQueDecide:
    @pytest.mark.asyncio
    async def test_a_tarefa_criada_DEPOIS_herda(self):
        token = set_current_tenant(UM_CLIENTE)
        try:
            assert await asyncio.create_task(_de_quem_sou()) == UM_CLIENTE.slug
        finally:
            reset_current_tenant(token)

    @pytest.mark.asyncio
    async def test_e_a_neta_tambem(self):
        """Se isto falhar, nenhum callback aninhado é de confiança."""

        async def mae() -> str:
            await asyncio.sleep(0)
            return await asyncio.create_task(_de_quem_sou())

        token = set_current_tenant(UM_CLIENTE)
        try:
            assert await asyncio.create_task(mae()) == UM_CLIENTE.slug
        finally:
            reset_current_tenant(token)

    @pytest.mark.asyncio
    async def test_mas_a_criada_ANTES_fica_na_PLATAFORMA(self):
        """O defeito, em quatro linhas.

        A tarefa nasce uma linha antes e vai para a base da plataforma —
        em silêncio, para sempre, mesmo que o contexto mude a seguir e
        mesmo que ela só corra muito depois.
        """
        orfa = asyncio.create_task(_de_quem_sou())
        token = set_current_tenant(UM_CLIENTE)
        try:
            assert await orfa == DEFAULT_TENANT_CONTEXT.slug, (
                "o comportamento da herança de contexto mudou — reler "
                "este ficheiro antes de concluir que é boa notícia"
            )
        finally:
            reset_current_tenant(token)


class TestOSilencioEOQueMata:
    def test_sem_ninguem_por_nada_e_a_plataforma(self):
        """Não é uma excepção: é a plataforma, caladinha.

        Se um dia isto passar a levantar erro, muitos caminhos vão
        começar a falhar — e será a melhor notícia do ano, porque hoje
        falham sem se ver.
        """
        assert current_tenant() is DEFAULT_TENANT_CONTEXT
        assert current_tenant().slug == "default"


class TestQuemFazTrabalhoDeClienteRecebeOContexto:
    """O padrão certo, fixado onde já está aplicado.

    Não impede que alguém escreva um caminho novo errado — isso é do
    `test_a_sessao_global_so_em_sitios_declarados.py`. Impede que alguém
    tire o argumento a quem já o tem, por achar que a variável de
    contexto basta.
    """

    def test_a_voz_recebe_o_ctx_por_argumento(self):
        from src.api.v1 import voice

        assert "ctx" in inspect.signature(voice._voice_answer).parameters, (  # noqa: SLF001
            "o `_voice_answer` deixou de receber o ctx — passa a depender "
            "da ordem do `set_current_tenant`, que é o defeito que este "
            "ficheiro documenta"
        )

    def test_e_usa_o_argumento_para_abrir_a_sessao(self):
        """Receber e não usar seria pior: parece resolvido."""
        from src.api.v1 import voice

        fonte = inspect.getsource(voice._voice_answer)  # noqa: SLF001
        assert "session_for(ctx)" in fonte, (
            "a voz recebe o ctx e abre a sessão por outro caminho"
        )
