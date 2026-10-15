# -*- coding: utf-8 -*-
"""Números em inglês numa conversa em castelhano (Lucas, 16/10/2026).

> «a voz fala em espanhol mas diz os números em inglês» («twelve thousand…»)

Com a tiffany/matthew em castelhano (poliglotas de base inglesa), o Sonic
lia os algarismos do resultado da ferramenta em inglês. A correcção: o
resultado vai com os números já escritos com letras na língua da conversa
(`por_extenso`), e a legenda volta a algarismos (`em_algarismos`).

Os testes seguem o caminho de produção: `ferramenta_do_cliente` →
`SessaoFalada._responder_ferramenta` (JSON) → o que o Sonic diz → legenda.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import pytest

from src.services import voz_fala_a_fala as falada
from src.services import voz_ponte_sonic as ponte
from src.services import voz_sessao_sonic as sonic
from src.services.numeros_falados import em_algarismos, numeros_no_formato, por_extenso

_ALGARISMO = re.compile(r"\d")


def _para_o_modelo(cru: str, lingua: str) -> str:
    return por_extenso(numeros_no_formato(cru, lingua), lingua)


# ── 1. O que vai para o modelo em castelhano não tem algarismos ─────


class TestCastelhanoPorExtenso:
    @pytest.mark.parametrize(
        "cru,esperado",
        [
            (
                "La Tienda 01 (Madrid) registró 4388 pedidos y facturó 563919.19 €.",
                "La Tienda cero uno (Madrid) registró cuatro mil trescientos ochenta y ocho "
                "pedidos y facturó quinientos sesenta y tres mil novecientos diecinueve "
                "coma diecinueve euros.",
            ),
            (
                "Tenéis 12 tiendas y 37 empleados.",
                "Tenéis doce tiendas y treinta y siete empleados.",
            ),
            (
                "El ticket medio fue de 128.45 € y el coste de 12350.70 €.",
                "El ticket medio fue de ciento veintiocho coma cuarenta y cinco euros y "
                "el coste de doce mil trescientos cincuenta coma setenta euros.",
            ),
            (
                "El 7.3 % de las entregas, un 12 % menos.",
                "El siete coma tres por ciento de las entregas, un doce por ciento menos.",
            ),
            (
                "Hay 158340 pedidos.",
                "Hay ciento cincuenta y ocho mil trescientos cuarenta pedidos.",
            ),
            ("Facturó 2000000 €.", "Facturó dos millones de euros."),
            ("Cuesta 0.05 €.", "Cuesta cero coma cero cinco euros."),
            ("En 2026 hubo 1 pedido.", "En dos mil veintiséis hubo un pedido."),
        ],
    )
    def test_os_numeros_vao_com_letras(self, cru, esperado):
        assert _para_o_modelo(cru, "es") == esperado

    @pytest.mark.parametrize(
        "cru,esperado",
        [
            ("Hay 21 pedidos y 21 tiendas.", "Hay veintiún pedidos y veintiuna tiendas."),
            ("Hay 200 tiendas en 200 días.", "Hay doscientas tiendas en doscientos días."),
            ("Una tienda: 1 tienda, 1 pedido.", "Una tienda: una tienda, un pedido."),
        ],
    )
    def test_genero_e_apocope(self, cru, esperado):
        assert _para_o_modelo(cru, "es") == esperado

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            (
                "El último pedido fue el 01/08/2026.",
                "El último pedido fue el uno de agosto de dos mil veintiséis.",
            ),
            (
                "Los datos acaban el 2026-08-01 a las 10:30.",
                "Los datos acaban el uno de agosto de dos mil veintiséis a las diez y treinta.",
            ),
            # Em algarismos, a voz dizia «O One».
            ("La Tienda 01 está en Madrid.", "La Tienda cero uno está en Madrid."),
            ("Facturó 1500000000 €.", "Facturó mil quinientos millones de euros."),
        ],
    )
    def test_datas_horas_e_codigos_tambem(self, texto, esperado):
        assert _para_o_modelo(texto, "es") == esperado

    @pytest.mark.parametrize(
        "dito,no_ecra",
        [
            (
                "El último pedido fue el uno de agosto de dos mil veintiséis.",
                "El último pedido fue el 1 de agosto de 2026.",
            ),
            ("La Tienda cero uno está en Madrid.", "La Tienda 01 está en Madrid."),
            # Sem mês nem código, «uno»/«cero» continuam palavras.
            ("Uno de los clientes tiene cero pedidos.", "Uno de los clientes tiene cero pedidos."),
        ],
    )
    def test_datas_e_codigos_voltam_a_algarismos_no_ecra(self, dito, no_ecra):
        assert em_algarismos(dito, "es") == no_ecra


class TestPortuguesPorExtenso:
    @pytest.mark.parametrize(
        "cru,esperado",
        [
            (
                "A loja faturou 563919.19 €.",
                "A loja faturou quinhentos e sessenta e três mil novecentos e dezanove "
                "vírgula dezanove euros.",
            ),
            ("Temos 1200 clientes.", "Temos mil e duzentos clientes."),
            ("Temos 1230 clientes.", "Temos mil duzentos e trinta clientes."),
            ("Temos 22 lojas e 200 lojas.", "Temos vinte e duas lojas e duzentas lojas."),
            ("Subiu 7.3 %.", "Subiu sete vírgula três por cento."),
        ],
    )
    def test_os_numeros_vao_com_letras(self, cru, esperado):
        assert _para_o_modelo(cru, "pt") == esperado


class TestInglesNaoMuda:
    @pytest.mark.parametrize("texto", ["Revenue was €563,919.19.", "We have 12 stores and 7.3 %."])
    def test_ingles_fica_em_algarismos(self, texto):
        assert por_extenso(texto, "en") == texto


# ── 2. A legenda volta a algarismos, em formato europeu ─────────────


class TestALegendaVoltaAAlgarismos:
    @pytest.mark.parametrize(
        "cru,lingua,no_ecra",
        [
            (
                "Facturó 563919.19 € con 4388 pedidos.",
                "es",
                "Facturó 563.919,19 euros con 4388 pedidos.",
            ),
            ("El 7.3 % de las entregas.", "es", "El 7,3 % de las entregas."),
            ("El coste fue de 12350.70 €.", "es", "El coste fue de 12.350,70 euros."),
            ("Hay 158340 pedidos.", "es", "Hay 158.340 pedidos."),
            ("A loja faturou 563919.19 €.", "pt", "A loja faturou 563.919,19 euros."),
            ("Temos 2345678 clientes.", "pt", "Temos 2.345.678 clientes."),
        ],
    )
    def test_ida_e_volta(self, cru, lingua, no_ecra):
        """O Sonic diz o que recebe; o servidor volta a pô-lo em algarismos."""
        dito = _para_o_modelo(cru, lingua)
        assert not _ALGARISMO.search(dito)
        assert em_algarismos(dito, lingua) == no_ecra


# ── 3. O caminho de produção, até ao `toolResult` ───────────────────


class _Entrada:
    def __init__(self) -> None:
        self.enviados: List[Dict[str, Any]] = []

    async def send(self, pedaco: Any) -> None:
        self.enviados.append(json.loads(pedaco.value.bytes_.decode("utf-8")))

    async def close(self) -> None:
        pass


async def _resultado_entregue(locale: str, resposta_do_motor: str) -> Dict[str, Any]:
    async def responder(*_a, **_k):
        return resposta_do_motor

    ferramenta = ponte.ferramenta_do_cliente(
        responder, user=None, page_id="p", ctx=None, locale=locale, space_id="s"
    )
    s = falada.SessaoFalada(ctx=None, ferramenta=ferramenta, instrucao="x", voz="tiffany")
    entrada = _Entrada()
    s._fluxo = type("F", (), {"input_stream": entrada})()
    await s._responder_ferramenta(
        {"toolUseId": "tu-1", "content": json.dumps({"pergunta": "¿cuánto?"})}
    )
    [tr] = [e["event"]["toolResult"] for e in entrada.enviados if "toolResult" in e["event"]]
    return json.loads(tr["content"])  # tem de ser JSON, senão o canal fecha


class TestOToolResult:
    @pytest.mark.asyncio
    async def test_em_castelhano_o_resultado_nao_leva_algarismos(self):
        corpo = await _resultado_entregue(
            "es", "La Tienda 01 (Madrid) registró 4388 pedidos y facturó 563919.19 €."
        )
        assert "cuatro mil trescientos ochenta y ocho pedidos" in corpo["resultado"]
        assert "coma diecinueve euros" in corpo["resultado"]
        # Nem o código da loja: em algarismos a voz dizia «O One».
        assert "Tienda cero uno" in corpo["resultado"]
        assert not _ALGARISMO.search(corpo["resultado"])
        assert "TAL E QUAL" in corpo["como_dizer"]

    @pytest.mark.asyncio
    async def test_em_ingles_o_resultado_fica_em_algarismos(self):
        corpo = await _resultado_entregue("en", "Revenue was 563919.19.")
        assert corpo["resultado"] == "Revenue was €563,919.19."

    @pytest.mark.asyncio
    async def test_em_portugues_tambem_fica_em_algarismos(self):
        """A ines e o leo são nativos e leem algarismos em português (medido
        10/10 a 16/10). Só muda se lá entrar uma voz poliglota."""
        corpo = await _resultado_entregue("pt", "A loja faturou 563919.19 €.")
        assert corpo["resultado"] == "A loja faturou 563.919,19 €."


# ── 4. A instrução de sistema: em castelhano, letras; nas outras, algarismos


class TestAInstrucao:
    def test_castelhano_pede_letras_e_ja_nao_pede_algarismos(self):
        texto = sonic.instrucao_de_sistema("es")
        assert "con letras y en español" in texto
        assert "nunca con cifras ni en inglés" in texto
        # A regra antiga («27.000») era a causa: a voz lia-a em inglês.
        assert "algarismos" not in texto
        assert "27.000" not in texto
        # O sotaque continua à cabeça.
        assert texto.startswith("Eres una voz de España.")

    @pytest.mark.parametrize("locale", ["pt", "en"])
    def test_as_outras_linguas_continuam_em_algarismos(self, locale):
        texto = sonic.instrucao_de_sistema(locale)
        assert "algarismos" in texto
        assert "con letras" not in texto


def test_nunca_rebenta():
    assert por_extenso("", "es") == ""
    assert por_extenso(None, "es") is None  # type: ignore[arg-type]
    # Números enormes ficam como estão em vez de sair mal lidos.
    assert por_extenso("Hay 1.234.567.890.123 filas.", "es") == "Hay 1.234.567.890.123 filas."
