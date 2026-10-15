# -*- coding: utf-8 -*-
"""Um deploy do sky-ai não pode chegar ao ecrã como «sem ligação» (14/10/2026).

Produção, 16:02 UTC: «¿Cuál es el ticket medio por canal?» deu 2/2

    Não foi possível contactar a Sky. Verifique a ligação e repita.

Dois defeitos na mesma frase:

1. **A causa não era a pergunta.** O `sky-ai` estava a ser substituído pelo
   deploy de #294 nesse minuto; o pod antigo fechou as ligações abertas e o
   `httpx` levantou um `NetworkError`. Dez minutos depois a mesma pergunta
   respondia em 5 s. Uma segunda tentativa, uns segundos depois, chega ao
   pod novo.
2. **Estava em português numa conversa em castelhano.** Com «Segue a sua
   pergunta» o `locale` chega `None` e a frase caía no `DEFAULT_LOCALE`.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from src.ai import http_client as hc
from src.core.locale import get_message, lingua_da_pergunta


class _Resposta:
    def __init__(self, dados):
        self._dados = dados

    def raise_for_status(self):
        return None

    def json(self):
        return self._dados


def _cliente_falso(falhas):
    """Um AsyncClient cujo `post` levanta as excepções de `falhas`, por
    ordem, e depois responde bem."""
    chamadas = {"n": 0}

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            chamadas["n"] += 1
            if falhas:
                raise falhas.pop(0)
            return _Resposta({"answer": "ok", "meta": {}})

    return _Cliente, chamadas


@pytest.fixture
def sem_plano_nem_espera(monkeypatch):
    from src.services import limites_do_plano

    async def _nada(*a, **k):
        return False

    monkeypatch.setattr(limites_do_plano, "reservar_pergunta_se_conta", _nada)
    monkeypatch.setattr(limites_do_plano, "devolver_pergunta", _nada)
    monkeypatch.setattr(hc, "ESPERA_ANTES_DE_REPETIR_S", 0)


def _pedido():
    return hc.AIServiceHTTPClient(base_url="http://sky-ai").query_connection(
        connection_id="c1",
        question="¿Cuál es el ticket medio por canal?",
        user_id="u1",
        space_id="s1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "erro",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadError("connection reset by peer"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
    ids=["connect", "reset", "disconnected"],
)
async def test_ligacao_perdida_no_deploy_tenta_outra_vez(monkeypatch, sem_plano_nem_espera, erro):
    cliente, chamadas = _cliente_falso([erro])
    monkeypatch.setattr(hc.httpx, "AsyncClient", cliente)
    r = await _pedido()
    assert r["answer"] == "ok"
    assert chamadas["n"] == 2


@pytest.mark.asyncio
async def test_tempo_esgotado_nao_se_repete(monkeypatch, sem_plano_nem_espera):
    # O sky-ai estava a trabalhar: repetir duplicava a espera para a mesma falha.
    cliente, chamadas = _cliente_falso([httpx.ReadTimeout("timeout")])
    monkeypatch.setattr(hc.httpx, "AsyncClient", cliente)
    with pytest.raises(httpx.TimeoutException):
        await _pedido()
    assert chamadas["n"] == 1


@pytest.mark.asyncio
async def test_so_se_repete_uma_vez(monkeypatch, sem_plano_nem_espera):
    cliente, chamadas = _cliente_falso(
        [httpx.ConnectError("x"), httpx.ConnectError("y"), httpx.ConnectError("z")]
    )
    monkeypatch.setattr(hc.httpx, "AsyncClient", cliente)
    with pytest.raises(httpx.ConnectError):
        await _pedido()
    assert chamadas["n"] == 2


@pytest.mark.parametrize(
    "pergunta,lingua",
    [
        ("¿Cuál es el ticket medio por canal?", "es"),
        ("Cuál es el ticket medio por canal", "es"),
        ("¿Qué cliente nos ha generado más facturación este año?", "es"),
        ("Quanto faturámos este mês?", "pt"),
        ("Qual foi a receita do mês?", "pt"),
        ("What were the top sales this year?", "en"),
        ("ok", None),
    ],
)
def test_a_lingua_da_pergunta(pergunta, lingua):
    assert lingua_da_pergunta(pergunta) == lingua


@pytest.mark.asyncio
async def test_a_frase_de_erro_segue_a_pergunta_com_locale_automatico():
    from src.services.ai_service import AIService

    class _Db:
        async def get(self, *a, **k):
            return SimpleNamespace(preferences={"language": "pt"})

    servico = AIService.__new__(AIService)
    servico.db = _Db()
    pedido = SimpleNamespace(locale=None, question="¿Cuál es el ticket medio por canal?")
    idioma = await servico._lingua_da_frase_de_erro("u1", pedido)
    assert idioma == "es"
    assert get_message("chat_error_network", idioma).startswith("No se ha podido")


@pytest.mark.asyncio
async def test_a_lingua_pedida_ganha_e_sem_pistas_vale_a_da_interface():
    from src.services.ai_service import AIService

    class _Db:
        async def get(self, *a, **k):
            return SimpleNamespace(preferences={"language": "es"})

    servico = AIService.__new__(AIService)
    servico.db = _Db()
    assert (
        await servico._lingua_da_frase_de_erro(
            "u1", SimpleNamespace(locale="en", question="¿Cuál es el ticket?")
        )
        == "en"
    )
    assert (
        await servico._lingua_da_frase_de_erro("u1", SimpleNamespace(locale=None, question="ok"))
        == "es"
    )
