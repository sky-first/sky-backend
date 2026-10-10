# -*- coding: utf-8 -*-
"""A vez volta à pessoa, e a Sky diz o que vai procurar.

> «Eu pergunto em vários idiomas, ele não responde… não está dizendo, por
>  exemplo, *ok, você quer saber quantos clientes vocês têm? Estou buscando
>  informação*.» — Lucas, 09/10/2026

Dois defeitos, e o primeiro escondia tudo o resto: depois da primeira
resposta a app ficava em `speaking` para sempre e deitava fora o microfone,
porque ninguém lhe dizia que a vez tinha voltado.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte
from src.services import voz_recado as recado
from src.services import voz_sessao_sonic as sonic
from src.tests.test_a_sessao_sonic_no_socket import _Ctx, _SessaoFalsa, _Socket, _start, _User


# ── A vez volta à pessoa ────────────────────────────────────────────


class TestAVezDaPessoa:
    def test_o_fim_da_fala_da_sky_devolve_o_microfone(self):
        assert ponte.para_o_protocolo(falada.VezDaPessoa()) == [
            {"type": "state", "value": "user_speaking"}
        ]

    @pytest.mark.asyncio
    async def test_so_o_fim_de_turno_do_audio_conta(self):
        """Um `INTERRUPTED` já tem o `Interrompido`; o texto não é a fala."""
        s = falada.SessaoFalada.__new__(falada.SessaoFalada)
        s._eventos = asyncio.Queue()
        s._ultimo_dito = None
        s._consultas = set()
        s.conta = falada.ContaDeTokens()

        await s._traduzir({"contentEnd": {"type": "AUDIO", "stopReason": "END_TURN"}})
        await s._traduzir({"contentEnd": {"type": "AUDIO", "stopReason": "INTERRUPTED"}})
        await s._traduzir({"contentEnd": {"type": "TEXT", "stopReason": "END_TURN"}})
        await s._traduzir({"contentEnd": {"type": "AUDIO", "role": "USER", "stopReason": "END_TURN"}})

        vistos = []
        while not s._eventos.empty():
            vistos.append(s._eventos.get_nowait())
        assert vistos == [falada.VezDaPessoa()]


# ── O que a Sky diz enquanto procura ────────────────────────────────


class TestAFraseDoRecado:
    @pytest.mark.parametrize(
        "pergunta,locale,frase",
        [
            ("Quantos clientes temos?", "pt", "Quer saber quantos clientes temos — vou ver."),
            ("qual foi a faturação de julho", "pt", "Quer saber qual foi a faturação de julho — vou ver."),
            ("¿Cuántos pedidos hubo ayer?", "es", "Quiere saber cuántos pedidos hubo ayer; déjeme mirarlo."),
            ("How many stores do we have?", "en", "You want to know how many stores do we have — let me check."),
        ],
    )
    def test_repete_a_pergunta_que_vai_responder(self, pergunta, locale, frase):
        assert recado.recado_de_espera(pergunta, locale) == frase

    @pytest.mark.parametrize(
        "pergunta,locale",
        [
            ("as vendas subiram?", "pt"),  # sim/não: não cabe em «quer saber»
            ("cuántos clientes tenemos", "pt"),  # outra língua: misturava duas
            ("", "pt"),
            ("quantos " + "clientes " * 20, "pt"),  # comprida demais para repetir
        ],
    )
    def test_quando_nao_cabe_diz_o_curto(self, pergunta, locale):
        assert recado.recado_de_espera(pergunta, locale) == "Deixe-me ver isso."

    def test_nao_estraga_uma_sigla(self):
        assert "IVA" in recado.recado_de_espera("Qual o IVA de julho?", "pt")
        assert recado.recado_de_espera("Qual o IVA?", "pt").startswith("Quer saber qual")

    def test_lingua_desconhecida_cai_no_ingles(self):
        assert recado.recado_de_espera("Wie viele Kunden?", "de") == "Let me check that."


# ── A coreografia: recado em paralelo, resultado depois ─────────────


async def _ferramenta_da_sessao(monkeypatch, linha: List[str], responder) -> tuple:
    """Corre a sessão e devolve a ferramenta que ela deu ao modelo."""
    apanhado: Dict[str, Any] = {}

    def fabricar(**kw):
        apanhado.update(kw)
        return _SessaoFalsa([])

    monkeypatch.setattr(sonic.falada, "SessaoFalada", fabricar, raising=True)
    s = _Socket([_start()])

    async def guardar(**_k):
        return None

    async def cliente():
        return object()

    await asyncio.wait_for(
        sonic.servir(s, user=_User(), ctx=_Ctx(), responder=responder,
                     persistir=guardar, abrir_cliente=cliente),
        timeout=5,
    )
    return apanhado["ferramenta"], s


@pytest.mark.asyncio
async def test_o_recado_sai_antes_da_resposta_e_nao_a_atrasa(monkeypatch):
    linha: List[str] = []
    monkeypatch.setenv("VOICE_SPOKEN_ACK", "1")

    async def sintetizar_falso(texto, voz):
        linha.append(f"recado:{voz}")
        await asyncio.sleep(0.05)
        yield b"\x01\x02" * 100

    monkeypatch.setattr(recado, "sintetizar", sintetizar_falso)

    async def responder(*_a, **_k):
        linha.append("consulta-comecou")
        await asyncio.sleep(0.01)
        linha.append("consulta-acabou")
        return "Há 12 lojas."

    ferramenta, s = await _ferramenta_da_sessao(monkeypatch, linha, responder)
    resultado = await ferramenta("Quantas lojas temos?")
    linha.append("devolveu-ao-modelo")

    assert "12 lojas" in resultado
    # Em paralelo: a consulta começou sem esperar pelo recado…
    assert linha.index("consulta-comecou") < linha.index("consulta-acabou")
    # …mas o resultado só seguiu depois de o som do recado ter saído.
    assert b"\x01\x02" * 100 in s.binario
    assert linha[-1] == "devolveu-ao-modelo"
    # A mesma voz do Sonic, e a frase também como legenda.
    assert "recado:ines" in linha
    assert {"type": "sky_text", "text": "Quer saber quantas lojas temos — vou ver."} in s.texto


@pytest.mark.asyncio
async def test_um_recado_que_falha_nao_leva_a_consulta_atras(monkeypatch):
    monkeypatch.setenv("VOICE_SPOKEN_ACK", "1")

    async def sintetizar_avariado(texto, voz):
        raise RuntimeError("Polly fora")
        yield b""  # pragma: no cover

    monkeypatch.setattr(recado, "sintetizar", sintetizar_avariado)

    async def responder(*_a, **_k):
        return "Há 12 lojas."

    ferramenta, _s = await _ferramenta_da_sessao(monkeypatch, [], responder)
    assert "12 lojas" in await ferramenta("Quantas lojas temos?")


@pytest.mark.asyncio
async def test_desligado_e_so_a_consulta(monkeypatch):
    monkeypatch.setenv("VOICE_SPOKEN_ACK", "0")
    chamado = []

    async def sintetizar_espiao(texto, voz):
        chamado.append(texto)
        yield b""

    monkeypatch.setattr(recado, "sintetizar", sintetizar_espiao)

    async def responder(*_a, **_k):
        return "Há 12 lojas."

    ferramenta, s = await _ferramenta_da_sessao(monkeypatch, [], responder)
    assert "12 lojas" in await ferramenta("Quantas lojas temos?")
    assert chamado == []
    assert not any(m.get("type") == "sky_text" for m in s.texto)
