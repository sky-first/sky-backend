# -*- coding: utf-8 -*-
"""Toda a chamada ao `sky-ai` diz a que cliente pertence.

> «cade aqui no sky universe todo o dado ao rededor desse globo de
>  raio? deveria aparecer todo o dado do cliente ai»
> — Lucas, 07/10/2026

Medido na base do cliente antes de mexer em nada:

    embeddings            188
    table_metadata        276

E o globo vazio.

── O defeito, que já é o terceiro da mesma família ─────────────────

O `sky-ai` escolhe a base de dados pelo `X-Tenant-Slug` do pedido
(Model B / Fase 5). Sem o cabeçalho vai à base da PLATAFORMA — e não
falha: procura ali, não encontra nada do cliente, e devolve uma lista
vazia. O ecrã lê isso correctamente como «não há nada aqui».

O `AIServiceHTTPClient` sempre o enviou. Quem não passa por essa
classe, não:

* o semeador sectorial (corrigido a 05/10 — «Connection not found»);
* a voz (corrigido ontem);
* o `/context/semantic-map`, que abre o seu próprio `httpx` — quatro
  chamadas;
* o `seed-embeddings` do `demo_service` — uma quinta.

── Porque é um teste e não só a correcção ──────────────────────────

Porque a correcção é invisível. Nada rebenta, nada aparece no log: o
produto responde com o conteúdo de outra base, ou com nada. Foi preciso
contar linhas em duas bases para o descobrir — três vezes.

A regra passa a viver numa função do módulo, e isto afirma que todos
os que falam com o `sky-ai` lhe chamam.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from src.ai import http_client
from src.ai.http_client import cabecalhos_do_cliente
from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)

RAIZ = Path(__file__).resolve().parents[1]


class TestOCabecalho:
    def test_sem_cliente_nao_manda_nada(self):
        """O caminho de omissão tem de ficar byte a byte na mesma.

        Um `X-Tenant-Slug: default` levava o `sky-ai` a procurar um
        cliente chamado «default» em vez de usar a base global.
        """
        token = set_current_tenant(DEFAULT_TENANT_CONTEXT)
        try:
            assert cabecalhos_do_cliente() == {}
        finally:
            reset_current_tenant(token)

    def test_com_cliente_manda_o_slug(self):
        from uuid import uuid4

        ctx = TenantContext(
            slug="skyfirstlabs", id=uuid4(), tier="pilot", display_name="SkyFirst Labs"
        )
        token = set_current_tenant(ctx)
        try:
            assert cabecalhos_do_cliente() == {"X-Tenant-Slug": "skyfirstlabs"}
        finally:
            reset_current_tenant(token)

    def test_nunca_levanta(self, monkeypatch):
        """Uma chamada à IA não pode ir abaixo por causa disto.

        Há caminhos de fundo — workers, tarefas agendadas — onde o
        contextvar pode não estar posto. O pior que pode acontecer é
        não mandar o cabeçalho.
        """

        def rebenta():
            raise RuntimeError("sem contexto")

        monkeypatch.setattr(
            "src.core.tenant_context.current_tenant", rebenta, raising=True
        )
        assert cabecalhos_do_cliente() == {}

    def test_a_classe_continua_a_usar_a_mesma_funcao(self):
        """Uma fonte só.

        Se a classe guardasse a sua cópia, corrigir uma deixava a outra
        para trás — e é exactamente assim que isto chegou a cinco
        sítios.
        """
        assert "cabecalhos_do_cliente()" in inspect.getsource(
            http_client.AIServiceHTTPClient._tenant_headers
        )


# ── a varredura ─────────────────────────────────────────────────────


def _chamadas_sem_cabecalho(caminho: Path) -> list[str]:
    """Clientes httpx abertos sem `headers=` no mesmo `with`."""
    fonte = caminho.read_text(encoding="utf-8")
    maus = []
    for m in re.finditer(r"httpx\.AsyncClient\(([^)]*)\)", fonte):
        if "headers" not in m.group(1):
            linha = fonte[: m.start()].count("\n") + 1
            maus.append(f"{caminho.name}:{linha}")
    return maus


#: Ficheiros em que **todas** as chamadas `httpx` vão ao `sky-ai`.
#:
#: Só estes é que podem ser varridos em bloco. O `demo_service`, por
#: exemplo, também fala com a Cloudflare (Turnstile) e com o Slack — e
#: mandar-lhes o `X-Tenant-Slug` seria dizer a terceiros a que cliente
#: pertence o pedido. A primeira versão deste teste chumbou por isso, e
#: tinha razão: «pôr o cabeçalho em todas» é a correcção errada.
SO_FALAM_COM_A_IA = [
    RAIZ / "api" / "v1" / "context_semantic.py",
]


@pytest.mark.parametrize("caminho", SO_FALAM_COM_A_IA, ids=lambda p: p.name)
def test_nenhuma_chamada_vai_sem_cabecalho(caminho: Path):
    maus = _chamadas_sem_cabecalho(caminho)
    assert not maus, (
        f"chamadas ao sky-ai sem `headers=cabecalhos_do_cliente()`: {maus} — "
        "o serviço vai à base da plataforma e devolve o conteúdo errado, "
        "em silêncio"
    )


def test_a_semente_de_embeddings_leva_o_cabecalho():
    """O `demo_service` fala com três sítios; só um é o `sky-ai`.

    Por isso aqui a afirmação é cirúrgica em vez de varrida: o cliente
    que faz o `seed-embeddings` leva os cabeçalhos, e os outros dois —
    Turnstile e Slack — ficam como estão.
    """
    from src.services import demo_service

    fonte = inspect.getsource(demo_service)
    i = fonte.index("/seed-embeddings")
    bloco = fonte[i : i + 1800]
    assert "headers=cabecalhos" in bloco


def test_e_os_terceiros_continuam_sem_saber_de_que_cliente_se_trata():
    """O contrapeso, e o erro que eu ia cometendo.

    A Cloudflare e o Slack não têm nada que saber o `slug` do cliente.
    Se alguém «arrumar» isto pondo o cabeçalho em todas as chamadas do
    ficheiro, é aqui que se dá por isso.
    """
    from src.services import demo_service

    fonte = inspect.getsource(demo_service)
    for terceiro in ("TURNSTILE_VERIFY_URL", "SLACK_DEMO_SIGNUPS_WEBHOOK"):
        i = fonte.index(terceiro)
        volta = fonte[max(0, i - 400) : i]
        assert "cabecalhos" not in volta, f"o {terceiro} passou a levar o cliente"


def test_a_varredura_encontra_chamadas(caminho=SO_FALAM_COM_A_IA[0]):
    """O contrapeso.

    Se o regex deixar de bater, o teste acima aprova tudo — incluindo
    um ficheiro onde alguém tirou os cabeçalhos todos.
    """
    fonte = caminho.read_text(encoding="utf-8")
    assert fonte.count("httpx.AsyncClient(") >= 4
    assert fonte.count("cabecalhos_do_cliente()") >= 4


def test_o_seed_le_os_cabecalhos_fora_da_tarefa():
    """E não lá dentro.

    O `create_task` copia o contexto, mas depender disso é depender de
    um detalhe do `asyncio` para decidir em que base de dados se
    escreve. Lidos no pedido, onde o contextvar está garantidamente
    posto.
    """
    from src.services import demo_service

    fonte = inspect.getsource(demo_service)
    i = fonte.index("cabecalhos = cabecalhos_do_cliente()")
    j = fonte.index("async def _fire()", i - 2000)
    assert i < j, "os cabeçalhos passaram para dentro da tarefa de fundo"
