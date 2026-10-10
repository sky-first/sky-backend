# -*- coding: utf-8 -*-
"""Números ditos por extenso passam a algarismos na legenda e no fio.

> «ele escreve "tienes veintisiete mil personas"… o correto era apresentar
>  um número» — Lucas, 10/10

O texto do Sonic é a transcrição do que ele DIZ, e por isso vem sempre por
extenso — pedir-lhe algarismos no prompt não muda nada (medido: «ciento
cincuenta y ocho mil trescientos cuarenta»). A voz fica como está; o que
se lê passa a «158.340».

Só converte sequências que são inequivocamente números. «Uno de los
clientes» e «um dos pedidos» ficam como estão: um número sozinho de 1
palavra só passa se vier antes de uma unidade («5 tiendas» sim, «una» não).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_UNIDADES: Dict[str, Dict[str, int]] = {
    "es": {
        "cero": 0,
        "uno": 1,
        "un": 1,
        "una": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciséis": 16,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
        "veintiuno": 21,
        "veintiún": 21,
        "veintiuna": 21,
        "veintidós": 22,
        "veintidos": 22,
        "veintitrés": 23,
        "veintitres": 23,
        "veinticuatro": 24,
        "veinticinco": 25,
        "veintiséis": 26,
        "veintiseis": 26,
        "veintisiete": 27,
        "veintiocho": 28,
        "veintinueve": 29,
        "treinta": 30,
        "cuarenta": 40,
        "cincuenta": 50,
        "sesenta": 60,
        "setenta": 70,
        "ochenta": 80,
        "noventa": 90,
        "cien": 100,
        "ciento": 100,
        "doscientos": 200,
        "doscientas": 200,
        "trescientos": 300,
        "trescientas": 300,
        "cuatrocientos": 400,
        "cuatrocientas": 400,
        "quinientos": 500,
        "quinientas": 500,
        "seiscientos": 600,
        "seiscientas": 600,
        "setecientos": 700,
        "setecientas": 700,
        "ochocientos": 800,
        "ochocientas": 800,
        "novecientos": 900,
        "novecientas": 900,
    },
    "pt": {
        "zero": 0,
        "um": 1,
        "uma": 1,
        "dois": 2,
        "duas": 2,
        "três": 3,
        "tres": 3,
        "quatro": 4,
        "cinco": 5,
        "seis": 6,
        "sete": 7,
        "oito": 8,
        "nove": 9,
        "dez": 10,
        "onze": 11,
        "doze": 12,
        "treze": 13,
        "catorze": 14,
        "quatorze": 14,
        "quinze": 15,
        "dezasseis": 16,
        "dezesseis": 16,
        "dezassete": 17,
        "dezessete": 17,
        "dezoito": 18,
        "dezanove": 19,
        "dezenove": 19,
        "vinte": 20,
        "trinta": 30,
        "quarenta": 40,
        "cinquenta": 50,
        "sessenta": 60,
        "setenta": 70,
        "oitenta": 80,
        "noventa": 90,
        "cem": 100,
        "cento": 100,
        "duzentos": 200,
        "duzentas": 200,
        "trezentos": 300,
        "trezentas": 300,
        "quatrocentos": 400,
        "quatrocentas": 400,
        "quinhentos": 500,
        "quinhentas": 500,
        "seiscentos": 600,
        "seiscentas": 600,
        "setecentos": 700,
        "setecentas": 700,
        "oitocentos": 800,
        "oitocentas": 800,
        "novecentos": 900,
        "novecentas": 900,
    },
    "en": {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    },
}
_CEM = {"en": {"hundred": 100}}
_ESCALAS = {
    "es": {"mil": 1000, "millón": 10**6, "millon": 10**6, "millones": 10**6},
    "pt": {"mil": 1000, "milhão": 10**6, "milhao": 10**6, "milhões": 10**6, "milhoes": 10**6},
    "en": {"thousand": 1000, "million": 10**6, "millions": 10**6},
}
_LIGA = {"es": {"y"}, "pt": {"e"}, "en": {"and"}}
_VIRGULA = {"es": {"coma"}, "pt": {"vírgula", "virgula"}, "en": {"point"}}
_PORCENTO = {
    "es": ("por ciento",),
    "pt": ("por cento",),
    "en": ("percent", "per cent"),
}
_PALAVRA = re.compile(r"[^\W\d_]+|\d+|[^\w\s]|\s+", re.UNICODE)


def _formatar(n: int, lingua: str) -> str:
    # Quatro algarismos ficam juntos: «2026», «1250» — é a norma (RAE e
    # Acordo), e é o que impede um ano de virar «2.026».
    if n < 10000:
        return str(n)
    s = f"{n:,}"
    return s if lingua == "en" else s.replace(",", ".")


def _ler_numero(tokens: List[str], i: int, lingua: str) -> Tuple[Optional[int], int, int]:
    """Lê um número a partir de `tokens[i]`. Devolve (valor, fim, palavras)."""
    if tokens[i].isspace():
        return None, i, 0  # o espaço antes do número é do texto, não dele
    un, esc, liga = _UNIDADES[lingua], _ESCALAS[lingua], _LIGA[lingua]
    cem = _CEM.get(lingua, {})
    total, grupo, palavras, j, fim = 0, 0, 0, i, i
    visto = False
    ultimo = 0  # o valor da última palavra lida: decide se um «y/e/and» liga
    while j < len(tokens):
        t = tokens[j].lower()
        if t.isspace():
            j += 1
            continue
        if t in un:
            # Só soma ao que vem antes se for o mesmo número: «twenty five»,
            # «ciento veinte», «mil doscientos». «Un cuatro por ciento» são
            # duas palavras soltas — um artigo e um 4, não 5.
            u = un[t]
            dezena = 20 <= ultimo <= 90 and ultimo % 10 == 0
            if visto and not ((dezena and u < 10) or (ultimo >= 100 and u < ultimo)):
                break
            grupo += u
            ultimo = un[t]
        elif t in cem and visto:
            grupo = (grupo or 1) * 100
            ultimo = 100
        elif t in esc:
            ultimo = esc[t]
            if esc[t] == 1000:
                total += (grupo or 1) * 1000
            else:
                total = (total + (grupo or 1)) * esc[t]
            grupo = 0
        elif t in liga and visto:
            # Só liga dentro de UM número: «treinta y dos», «cento e vinte»,
            # «mil e duzentos». «Entre tres y cuatro» são dois — não 7.
            k = j + 1
            while k < len(tokens) and tokens[k].isspace():
                k += 1
            seguinte = un.get(tokens[k].lower()) if k < len(tokens) else None
            dezena = 20 <= ultimo <= 90 and ultimo % 10 == 0
            if seguinte is not None and (
                (dezena and seguinte < 10) or (ultimo >= 100 and seguinte < ultimo)
            ):
                j = k
                continue
            break
        else:
            break
        visto = True
        palavras += 1
        j += 1
        fim = j
    if not visto:
        return None, i, 0
    return total + grupo, fim, palavras


def em_algarismos(texto: str, lingua: str = "es") -> str:
    """«veintisiete mil personas» → «27.000 personas». Nunca rebenta."""
    lingua = (lingua or "es")[:2]
    if lingua not in _UNIDADES or not texto:
        return texto
    try:
        # «por cento» antes de tudo: senão o «cento» lia-se como 100.
        for p in _PORCENTO[lingua]:
            texto = re.sub(r"\s+" + p + r"\b", " %", texto, flags=re.I)
        tokens = _PALAVRA.findall(texto)
        out: List[str] = []
        i = 0
        while i < len(tokens):
            valor, fim, palavras = _ler_numero(tokens, i, lingua)
            if valor is None:
                out.append(tokens[i])
                i += 1
                continue
            # Decimais: «cuatro coma cinco».
            decimal = None
            k = fim
            while k < len(tokens) and tokens[k].isspace():
                k += 1
            if k < len(tokens) and tokens[k].lower() in _VIRGULA[lingua]:
                k += 1
                while k < len(tokens) and tokens[k].isspace():
                    k += 1
                dec, fim2, _ = _ler_numero(tokens, k, lingua) if k < len(tokens) else (None, k, 0)
                if dec is not None:
                    decimal, fim = dec, fim2
            # Uma palavra só («uno», «um», «one») é quase sempre artigo ou
            # pronome. Só mudam os de duas ou mais palavras, ≥ 10, com
            # decimais, ou seguidos de «%».
            k = fim
            while k < len(tokens) and tokens[k].isspace():
                k += 1
            percentagem = k < len(tokens) and tokens[k] == "%"
            if palavras == 1 and valor < 10 and decimal is None and not percentagem:
                out.extend(tokens[i:fim])
                i = fim
                continue
            numero = _formatar(valor, lingua)
            if decimal is not None:
                numero += ("." if lingua == "en" else ",") + str(decimal)
            out.append(numero)
            i = fim
        return "".join(out)
    except Exception:  # noqa: BLE001 — uma legenda nunca pode partir a voz
        return texto
