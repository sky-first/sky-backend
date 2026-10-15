# -*- coding: utf-8 -*-
"""«por» antes de um número é preposição, não «por cento» (Lucas, 16/10/2026).

> «Tienda 01 registró ventas % 82.304,18 euros.»

O Sonic disse «registró ventas por ciento ochenta y dos mil trescientos
cuatro coma dieciocho euros» (182.304,18 €, dito por extenso desde o #773).
A legenda trocava «por ciento» por «%» antes de ler o número: o «por»
sumia, e o «ciento» do número também — o ecrã mostrava 82 mil em vez de
182 mil.

Regra: «X por ciento» (número ANTES) é «X %»; «por» + número fica.
"""
from __future__ import annotations

import pytest

from src.services.numeros_falados import em_algarismos, numeros_no_formato, por_extenso


@pytest.mark.parametrize(
    "dito,esperado",
    [
        # O caso do Lucas, tal e qual o Sonic o disse.
        (
            "La Tienda cero uno registró ventas por ciento ochenta y dos mil "
            "trescientos cuatro coma dieciocho euros.",
            "La Tienda 01 registró ventas por 182.304,18 euros.",
        ),
        (
            "registró ventas por ochenta y dos mil trescientos cuatro coma dieciocho euros",
            "registró ventas por 82.304,18 euros",
        ),
        ("un siete coma tres por ciento", "un 7,3 %"),
        ("el cien por cien de las tiendas", "el 100 % de las tiendas"),
        ("un cuatro por ciento menos", "un 4 % menos"),
        ("el doce por ciento de los pedidos", "el 12 % de los pedidos"),
        ("por cada euro", "por cada euro"),
        ("multiplicado por dos", "multiplicado por dos"),
        ("dividido por tres", "dividido por tres"),
        ("dividido por doce", "dividido por 12"),
        # Ambíguo — decidido: sem número ANTES, «por» é preposição e o
        # «ciento» começa o número seguinte.
        ("por ciento veinte euros", "por 120 euros"),
        (
            "el doce por ciento de los pedidos, por ciento veinte mil euros",
            "el 12 % de los pedidos, por 120.000 euros",
        ),
        # Algarismos crus também.
        ("el 7 por ciento", "el 7 %"),
    ],
)
def test_castelhano(dito, esperado):
    assert em_algarismos(dito, "es") == esperado


@pytest.mark.parametrize(
    "dito,esperado",
    [
        ("faturou por cento e vinte mil euros", "faturou por 120.000 euros"),
        ("sete vírgula três por cento das entregas", "7,3 % das entregas"),
        ("vendas por duzentos euros", "vendas por 200 euros"),
        ("dividido por três", "dividido por três"),
        ("doze por cento menos do que em agosto", "12 % menos do que em agosto"),
    ],
)
def test_portugues(dito, esperado):
    assert em_algarismos(dito, "pt") == esperado


@pytest.mark.parametrize(
    "dito,esperado",
    [
        ("seven point three percent", "7.3 %"),
        ("twelve per cent of orders", "12 % of orders"),
        ("what percent of orders were late", "what percent of orders were late"),
    ],
)
def test_ingles(dito, esperado):
    assert em_algarismos(dito, "en") == esperado


@pytest.mark.parametrize(
    "cru,lingua",
    [
        ("La Tienda 01 registró ventas por 182304.18 €.", "es"),
        ("La Tienda 01 registró ventas por 120.00 € y un 7.3 % de mermas.", "es"),
        ("A Loja 01 faturou por 150000 €.", "pt"),
    ],
)
def test_ida_e_volta_nao_perde_o_por_nem_o_cento(cru, lingua):
    """O que vai para o modelo (por extenso) e volta para o ecrã não muda."""
    dito = por_extenso(numeros_no_formato(cru, lingua), lingua)
    volta = em_algarismos(dito, lingua)
    assert volta == numeros_no_formato(cru, lingua).replace("€", "euros")
    assert "%" not in volta.split("por", 1)[1].split("euros", 1)[0]
