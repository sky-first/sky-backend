# -*- coding: utf-8 -*-
"""Números em formato europeu, para o texto das respostas.

Os cartões são formatados pelo `KpiWidget`, que usa o `Intl` do browser
com a língua activa. O texto das respostas é construído aqui, em Python,
e tem de sair com o mesmo aspecto — ponto nos milhares, vírgula nos
decimais.

Se os dois divergirem, o mesmo número aparece de duas maneiras no mesmo
ecrã, e isso custa mais confiança do que vale.

Não é uma biblioteca de localização: é castelhano e português, que
partilham estas regras. No dia em que houver uma demonstração em inglês
isto passa a precisar de saber a língua — e nessa altura o sítio certo
é o `locale`, não um `if` aqui dentro.
"""

from __future__ import annotations

from typing import Any


def _agrupa(texto: str) -> str:
    """`1,234,567.89` → `1.234.567,89`."""
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def n(valor: Any) -> str:
    """Um inteiro com separador de milhares: `246.853`."""
    if valor is None:
        return "—"
    return _agrupa(f"{float(valor):,.0f}")


def eur(valor: Any) -> str:
    """Dinheiro sem cêntimos: `1.862.227 €`.

    Sem cêntimos de propósito, e pela mesma razão que o construtor de
    KPIs os corta acima dos 100 €: numa frase sobre um milhão de euros,
    os cêntimos são ruído que empurra o número que interessa para o fim
    da linha.
    """
    if valor is None:
        return "—"
    return _agrupa(f"{float(valor):,.0f}") + " €"


def euro2(valor: Any) -> str:
    """Dinheiro com cêntimos: `1,49 €`.

    Para as ordens de grandeza onde os cêntimos *são* o argumento —
    1,20 €/km contra 1,49 €/km é a diferença entre perder e ganhar.
    """
    if valor is None:
        return "—"
    return _agrupa(f"{float(valor):,.2f}") + " €"


def pct(valor: Any) -> str:
    """Uma percentagem já em 0–100: `19,7 %`.

    Em 0–100 e não em 0–1, ao contrário do que o `KpiWidget` espera. É
    uma divergência deliberada: aqui o valor vem de um `SELECT
    ROUND(100.0 * ...)` e convertê-lo para fracção só para o voltar a
    multiplicar é uma viagem de ida e volta onde se perde precisão e
    não se ganha nada.
    """
    if valor is None:
        return "—"
    return f"{float(valor):.1f}".replace(".", ",") + " %"
