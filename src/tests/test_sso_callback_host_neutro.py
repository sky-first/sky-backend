"""O retorno do SSO num host que não pertence a cliente nenhum.

Porque existe este caso:

O ``state`` passou a ser assinado e preso ao cliente, e o retorno é verificado
contra o cliente do *callback* (achado A3). Para a web isso chega — o callback
cai numa página do Next.js e o frontend consegue mandar ``X-Tenant-Slug``.

Para a app nativa não chega: fecha a porta. A app fala com ``api.<base>``, um
host neutro que serve todos os clientes, e **a Google não devolve o
``?tenant=``** no retorno — devolve apenas o que ela própria põe na query. No
callback não há sub-domínio, nem cabeçalho, nem JWT, nem parâmetro. O
``_slug_from_request`` devolve ``None``, o ``state`` diz o cliente, e o retorno
era recusado em **100% das tentativas**:

    SSO callback recusado (provider=google, tenant=<plataforma>):
        state pertence a outro cliente

A correção: num host que não resolve cliente, a autoridade passa a ser o
``state`` assinado. Não é uma excepção ao A3 — é a mesma regra com a única fonte
que existe naquele caminho. Ver docs/SEGURANCA-SSO-E-ISOLAMENTO-TENANT.md §8.

Estes testes cobrem a decisão de "qual é o cliente esperado" com as funções
verdadeiras, que é onde o defeito estava.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.api.v1.auth import _slug_from_request
from src.core import sso_state
from src.core.sso_state import (
    SSOStateError,
    issue_state,
    tenant_from_state,
    verify_state,
)


def _pedido(*, host: str = "api.skyfirstlabs.com", cabecalhos=None, query=None):
    """Um retorno da Google: sem cabeçalhos nossos e sem `?tenant=`."""
    return SimpleNamespace(
        headers={"host": host, **(cabecalhos or {})},
        query_params=query or {},
    )


def _cliente_esperado(pedido, state):
    """A decisão que o handler toma, com as funções verdadeiras."""
    return _slug_from_request(pedido) or tenant_from_state(state)


# ── 1. o caso que estava partido ────────────────────────────────────────────

def test_host_neutro_tira_o_cliente_do_state():
    state = issue_state("skyfirstlabs", "sky://auth")
    pedido = _pedido()  # como a Google devolve: nada que identifique o cliente

    assert _slug_from_request(pedido) is None, "o host neutro não resolve cliente"
    assert _cliente_esperado(pedido, state) == "skyfirstlabs"
    verify_state(state, _cliente_esperado(pedido, state))  # não levanta


# ── 2 a 4. o que continua a ser recusado no host neutro ─────────────────────

def test_state_forjado_morre_na_assinatura():
    forjado = "eyJ0IjoiZ2J0In0.assinaturaqueninguemtem"
    assert tenant_from_state(forjado) is None
    with pytest.raises(SSOStateError):
        verify_state(forjado, _cliente_esperado(_pedido(), forjado))


def test_state_expirado_e_recusado(monkeypatch):
    antigo = issue_state("skyfirstlabs", "sky://auth")
    # Uma hora depois. O TTL são 5 minutos.
    #
    # O instante real fica preso agora, ANTES de substituir a função: um
    # `lambda` que chamasse `time.time()` chamaria a substituição a si própria.
    agora = time.time()
    monkeypatch.setattr(sso_state.time, "time", lambda: agora + 3600)
    with pytest.raises(SSOStateError, match="expirado"):
        verify_state(antigo, _cliente_esperado(_pedido(), antigo))


def test_sem_state_nao_ha_entrada():
    assert tenant_from_state(None) is None
    assert _cliente_esperado(_pedido(), None) is None
    with pytest.raises(SSOStateError):
        verify_state(None, None)


# ── 5 e 6. o A3 mantém-se onde o host manda ─────────────────────────────────

def test_num_host_de_cliente_o_host_ganha_ao_state():
    """O que o A3 impede continua impedido.

    Um `state` emitido para outro cliente não serve num host que já diz a que
    cliente pertence — é este o caso que a fonte nova NÃO pode enfraquecer.
    """
    state_de_outro = issue_state("gbtsolutions", "sky://auth")
    pedido = _pedido(host="workspace-skyfirstlabs.skyfirstlabs.com")

    assert _cliente_esperado(pedido, state_de_outro) == "skyfirstlabs"
    with pytest.raises(SSOStateError, match="outro cliente"):
        verify_state(state_de_outro, _cliente_esperado(pedido, state_de_outro))


def test_num_host_de_cliente_o_state_do_mesmo_cliente_passa():
    state = issue_state("skyfirstlabs", "sky://auth")
    pedido = _pedido(host="workspace-skyfirstlabs.skyfirstlabs.com")
    verify_state(state, _cliente_esperado(pedido, state))  # não levanta


def test_o_cabecalho_continua_a_ganhar_ao_state():
    """Quem consegue mandar cabeçalhos não passa a depender do state."""
    state = issue_state("gbtsolutions", "sky://auth")
    pedido = _pedido(cabecalhos={"x-tenant-slug": "sandbox"})
    assert _cliente_esperado(pedido, state) == "sandbox"


# ── 7. o cliente chega ao código de entrega ─────────────────────────────────

def test_o_cliente_do_state_nao_e_vazio():
    """O `sky_code` leva o cliente consigo.

    Ia `callback_tenant or ""` — com o cliente a resolver para `None`, a app
    recebia um código preso a "" e a troca seguinte perdia o cliente.
    """
    state = issue_state("skyfirstlabs", "sky://auth")
    assert _cliente_esperado(_pedido(), state) == "skyfirstlabs"
