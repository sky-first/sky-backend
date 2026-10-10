# -*- coding: utf-8 -*-
"""O Live Talk do Lucas a 10/10/2026, em castelhano, com a voz «Carlos».

> «¿Quantos clientes eu tenho?» — uma pergunta em português com o «¿» do
>  castelhano, porque a SESSÃO era em espanhol.
> «Has facturado un total de six million one hundred fifty three thousand
>  one hundred eighty five point seventy two.» — números em inglês numa
>  resposta em castelhano.
> «Diz só "El usuario" e corta; depois escreve a resposta calado.»
> «ws_error», a vermelho, depois de silenciar.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from src.core.tenant_context import TenantContext
from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte
from src.services import voz_sessao_sonic as sonic
from src.services.numeros_falados import em_algarismos, numeros_no_formato
from src.services.pontuacao import e_castelhano, pontuar_pergunta

# ── 1. O «¿» decide-o o texto ───────────────────────────────────────


class TestOInterrogacaoInicialSegueOTexto:
    @pytest.mark.parametrize(
        "dito,lingua,lido",
        [
            # O caso visto: sessão em castelhano, pergunta em português.
            ("quantos clientes eu tenho", "es", "Quantos clientes eu tenho?"),
            ("¿Quantos clientes eu tenho?", "es", "Quantos clientes eu tenho?"),
            ("qual foi a faturação de julho", "es", "Qual foi a faturação de julho?"),
            ("quantas lojas temos", "es", "Quantas lojas temos?"),
            # E o contrário: castelhano numa sessão em português leva-o.
            ("cuánto he facturado", "pt", "¿Cuánto he facturado?"),
            ("cuántos clientes tengo", "es", "¿Cuántos clientes tengo?"),
            ("cuantos clientes tenemos", "pt", "¿Cuantos clientes tenemos?"),
            ("qué día es hoy", "es", "¿Qué día es hoy?"),
            ("dónde hay más ventas", "es", "¿Dónde hay más ventas?"),
            # Inglês nunca.
            ("how many stores do we have", "es", "How many stores do we have?"),
            # Sem palavras que decidam, vale a língua da sessão.
            ("como estás", "es", "¿Como estás?"),
            ("como estás", "pt", "Como estás?"),
        ],
    )
    def test_o_texto_manda(self, dito, lingua, lido):
        assert pontuar_pergunta(dito, lingua) == lido

    def test_a_deteccao(self):
        assert e_castelhano("Quantos clientes eu tenho?") is False
        assert e_castelhano("¿Cuántos clientes tengo?") is True
        assert e_castelhano("como estás") is None


# ── 2a. A legenda lê números ditos noutra língua ────────────────────


class TestNumerosDeOutraLingua:
    def test_o_caso_do_lucas(self):
        dito = (
            "Has facturado un total de six million one hundred fifty three thousand "
            "one hundred eighty five point seventy two."
        )
        assert em_algarismos(dito, "es") == "Has facturado un total de 6.153.185,72."

    def test_em_portugues_tambem(self):
        assert (
            em_algarismos("Faturaste six million one hundred thousand.", "pt")
            == "Faturaste 6.100.000."
        )

    def test_portugues_numa_conversa_em_castelhano(self):
        assert em_algarismos("Tienes vinte e sete mil pessoas.", "es") == "Tienes 27.000 pessoas."

    def test_decimais_digito_a_digito(self):
        assert em_algarismos("The margin is four point five percent.", "es") == (
            "The margin is 4,5 %."
        )
        assert em_algarismos("It grew twenty point seven five.", "en") == "It grew 20.75."

    @pytest.mark.parametrize(
        "dito",
        [
            "Ten en cuenta que hay más pedidos.",  # «ten» castelhano, não 10
            "Un punto de venta cerró.",
            "Entre tres y cuatro tiendas.",
        ],
    )
    def test_palavra_solta_de_outra_lingua_fica(self, dito):
        assert em_algarismos(dito, "es") == dito

    def test_a_lingua_da_conversa_continua_a_valer(self):
        assert em_algarismos("Hoy es diez de octubre de dos mil veintiséis.", "es") == (
            "Hoy es 10 de octubre de 2026."
        )


# ── 2b. O que vai para o modelo leva os números já formatados ───────


class TestNumerosParaOModelo:
    @pytest.mark.parametrize(
        "resultado,lingua,esperado",
        [
            (
                "Has facturado un total de 6153185.72 en 2026.",
                "es",
                "Has facturado un total de 6.153.185,72 € en 2026.",
            ),
            (
                "Faturaste 6153185.72 este ano.",
                "pt",
                "Faturaste 6.153.185,72 € este ano.",
            ),
            (
                "Total revenue was 6153185.72.",
                "en",
                "Total revenue was €6,153,185.72.",
            ),
            ("El importe es 300 euros.", "es", "El importe es 300 €."),
            ("Las ventas fueron EUR 1250.5.", "es", "Las ventas fueron 1250,5 €."),
            ("Hay 158340 pedidos.", "es", "Hay 158.340 pedidos."),
        ],
    )
    def test_formata_na_lingua_da_conversa(self, resultado, lingua, esperado):
        assert numeros_no_formato(resultado, lingua) == esperado

    @pytest.mark.parametrize(
        "resultado",
        [
            "Los datos acaban el 2026-08-01 a las 10:30.",
            "Versión 1.2.3 del informe.",
            "Ya formateado: 6.153.185,72 € y 1.250 tiendas.",
            "Tienes 12 tiendas en 2026.",
        ],
    )
    def test_nao_toca_no_que_nao_e_numero_cru(self, resultado):
        assert numeros_no_formato(resultado, "es") == resultado

    @pytest.mark.asyncio
    async def test_a_ferramenta_ja_devolve_formatado(self):
        async def responder(*_a, **_k):
            return "Has facturado un total de 6153185.72."

        f = ponte.ferramenta_do_cliente(
            responder, user=None, page_id="p", ctx=None, locale="es", space_id="s"
        )
        assert await f("¿cuánto he facturado?") == "Has facturado un total de 6.153.185,72 €."

    def test_o_modelo_e_mandado_ler_na_lingua_da_conversa(self):
        texto = sonic.instrucao_de_sistema("es")
        assert "euros" in texto
        assert "nunca noutra língua" in texto


# ── 3. O texto do Sonic: interrupção e as duas versões de cada frase ─

UM_CLIENTE = TenantContext(slug="cliente-de-teste", id=uuid4(), tier="pro", display_name="C")


def _sessao() -> falada.SessaoFalada:
    async def nada(_p: str) -> str:
        return "{}"

    return falada.SessaoFalada(ctx=UM_CLIENTE, ferramenta=nada, instrucao="x", voz="carlos")


def _texto(conteudo: str, cid: str, role: str = "ASSISTANT") -> Dict[str, Any]:
    return {"textOutput": {"content": conteudo, "contentId": cid, "role": role}}


def _inicio(cid: str, estagio: str) -> Dict[str, Any]:
    return {
        "contentStart": {
            "type": "TEXT",
            "role": "ASSISTANT",
            "contentId": cid,
            "additionalModelFields": json.dumps({"generationStage": estagio}),
        }
    }


async def _eventos(s: falada.SessaoFalada, brutos: List[Dict[str, Any]]) -> List[Any]:
    for ev in brutos:
        await s._traduzir(ev)
    fora = []
    while not s._eventos.empty():
        fora.append(s._eventos.get_nowait())
    return fora


class TestOTextoDoSonic:
    @pytest.mark.asyncio
    async def test_a_marca_de_interrupcao_nao_e_legenda(self):
        """`{ "interrupted" : true }` vinha para o ecrã como fala."""
        fora = await _eventos(_sessao(), [_texto('{ "interrupted" : true }', "c1")])
        assert [type(e) for e in fora] == [falada.Interrompido]

    @pytest.mark.asyncio
    async def test_a_versao_final_nao_escreve_a_resposta_outra_vez(self):
        """SPECULATIVE chega antes do som (é a legenda); FINAL depois, às
        vezes com outras palavras. As duas juntavam-se na legenda."""
        fora = await _eventos(
            _sessao(),
            [
                _inicio("a", "SPECULATIVE"),
                _texto("Has facturado 6.153.185,72 euros.", "a"),
                {"audioOutput": {"content": "AAAA"}},
                _inicio("b", "FINAL"),
                _texto("El usuario ha facturado 6.153.185,72 euros.", "b"),
            ],
        )
        ditos = [e.texto for e in fora if isinstance(e, falada.Dito)]
        assert ditos == ["Has facturado 6.153.185,72 euros."]

    @pytest.mark.asyncio
    async def test_sem_estagio_tudo_continua_como_estava(self):
        fora = await _eventos(_sessao(), [_texto("Hola.", "a"), _texto("Adiós.", "b")])
        assert [e.texto for e in fora if isinstance(e, falada.Dito)] == ["Hola.", "Adiós."]

    @pytest.mark.asyncio
    async def test_a_transcricao_da_pessoa_passa_sempre(self):
        fora = await _eventos(
            _sessao(),
            [_inicio("a", "SPECULATIVE"), _texto("Hola.", "a"), _texto("cuánto", "u", "USER")],
        )
        assert any(isinstance(e, falada.Ouvido) for e in fora)


# ── 4. O socket não fica calado ─────────────────────────────────────


class _SocketLento:
    """Fica aberto ~0,4 s sem a pessoa dizer nada — silenciada."""

    def __init__(self) -> None:
        self.texto: List[Dict[str, Any]] = []
        self._start = True

    async def receive(self) -> Dict[str, Any]:
        if self._start:
            self._start = False
            return {
                "text": json.dumps(
                    {"type": "control", "action": "start", "page_id": "p", "locale": "es"}
                )
            }
        await asyncio.sleep(0.4)
        return {"type": "websocket.disconnect"}

    async def send_text(self, s: str) -> None:
        self.texto.append(json.loads(s))

    async def send_bytes(self, _b: bytes) -> None:
        pass

    async def close(self, code: int = 1000) -> None:
        pass


class _SessaoParada:
    def __init__(self) -> None:
        self.conta = falada.ContaDeTokens()
        self._fim = asyncio.Event()

    async def abrir(self, _c: Any) -> None:
        pass

    async def fechar(self) -> None:
        self._fim.set()

    async def ouvir_microfone(self, _pcm: bytes) -> None:
        pass

    async def silencio(self, _s: float = 0.0) -> None:
        pass

    async def escutar(self) -> None:
        await self._fim.wait()

    def eventos(self):
        async def gerar():
            await self._fim.wait()
            if False:  # pragma: no cover
                yield None

        return gerar()


@pytest.mark.asyncio
async def test_com_a_pessoa_calada_o_socket_continua_a_ver_trafego(monkeypatch):
    monkeypatch.setattr(sonic, "BATIDA_DO_SOCKET", 0.05)
    monkeypatch.setattr(sonic, "BATIDA_DO_SILENCIO", 0.05)
    monkeypatch.setattr(sonic.recado, "ligado", lambda: False)
    monkeypatch.setattr(sonic.legenda_viva, "esta_ligada", lambda: False)
    sessao = _SessaoParada()
    monkeypatch.setattr(sonic.falada, "SessaoFalada", lambda **_kw: sessao)
    s = _SocketLento()

    async def nada(*_a, **_k):
        return None

    async def cliente():
        return object()

    await asyncio.wait_for(
        sonic.servir(s, user=None, ctx=None, responder=nada, persistir=nada, abrir_cliente=cliente),
        timeout=5,
    )
    assert any(m.get("type") == "keepalive" for m in s.texto)
