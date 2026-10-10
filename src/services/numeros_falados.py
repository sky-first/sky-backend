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


def _saltar_espacos(tokens: List[str], k: int) -> int:
    while k < len(tokens) and tokens[k].isspace():
        k += 1
    return k


def _ler_decimais(tokens: List[str], k: int, lingua: str) -> Tuple[Optional[str], int]:
    """Os decimais depois de «coma»/«vírgula»/«point». Devolve (dígitos, fim).

    Dois jeitos de os dizer, e os dois aparecem: «setenta y dos» (um número)
    e «seven two» (dígito a dígito, como se diz em inglês). O segundo lia-se
    como «7» e deixava o «two» solto na legenda.
    """
    dec, fim, palavras = _ler_numero(tokens, k, lingua)
    if dec is None:
        return None, k
    digitos = str(dec)
    if palavras == 1 and dec < 10:
        while True:
            j = _saltar_espacos(tokens, fim)
            if j >= len(tokens) or tokens[j].lower() not in _UNIDADES[lingua]:
                break
            mais, fim2, p2 = _ler_numero(tokens, j, lingua)
            if mais is None or p2 != 1 or mais >= 10:
                break
            digitos += str(mais)
            fim = fim2
    return digitos, fim


def em_algarismos(texto: str, lingua: str = "es") -> str:
    """«veintisiete mil personas» → «27.000 personas». Nunca rebenta.

    ── Lê as três línguas, escreve na da conversa ──────────────────────

    > «Has facturado un total de six million one hundred fifty three
    >  thousand one hundred eighty five point seventy two.» — legenda vista
    >  pelo Lucas a 10/10, numa conversa em castelhano.

    O Sonic às vezes diz os números NOUTRA língua (leu um 6153185.72 cru em
    inglês). Só se tentava a língua da conversa, e o inglês passava tal e
    qual para o ecrã. Agora, em cada posição, tenta-se a língua da conversa
    e as outras, e fica a leitura que apanha mais palavras. O número sai
    sempre no formato da conversa: «6.153.185,72».

    Uma palavra SOLTA de outra língua nunca muda: «ten en cuenta» é
    castelhano, não um 10.
    """
    lingua = (lingua or "es")[:2]
    if lingua not in _UNIDADES or not texto:
        return texto
    linguas = [lingua] + [x for x in _UNIDADES if x != lingua]
    try:
        # «por cento» antes de tudo: senão o «cento» lia-se como 100.
        for lg in linguas:
            for p in _PORCENTO[lg]:
                texto = re.sub(r"\s+" + p + r"\b", " %", texto, flags=re.I)
        tokens = _PALAVRA.findall(texto)
        out: List[str] = []
        i = 0
        while i < len(tokens):
            # A leitura que apanha mais palavras; num empate, a da conversa.
            valor, fim, palavras, lg = None, i, 0, lingua
            for cand in linguas:
                v, f, p = _ler_numero(tokens, i, cand)
                if v is None or p <= palavras:
                    continue
                if cand != lingua and p < 2:
                    # Uma palavra solta de outra língua fica como está — a
                    # menos que traga decimais: «four point five».
                    k = _saltar_espacos(tokens, f)
                    if not (k < len(tokens) and tokens[k].lower() in _VIRGULA[cand]):
                        continue
                valor, fim, palavras, lg = v, f, p, cand
            if valor is None:
                out.append(tokens[i])
                i += 1
                continue
            # Decimais: «cuatro coma cinco», «point seventy two».
            decimal = None
            k = _saltar_espacos(tokens, fim)
            if k < len(tokens) and tokens[k].lower() in _VIRGULA[lg]:
                k = _saltar_espacos(tokens, k + 1)
                if k < len(tokens):
                    dec, fim2 = _ler_decimais(tokens, k, lg)
                    if dec is not None:
                        decimal, fim = dec, fim2
            # Uma palavra só («uno», «um», «one») é quase sempre artigo ou
            # pronome. Só mudam os de duas ou mais palavras, ≥ 10, com
            # decimais, ou seguidos de «%».
            k = _saltar_espacos(tokens, fim)
            percentagem = k < len(tokens) and tokens[k] == "%"
            if palavras == 1 and valor < 10 and decimal is None and not percentagem:
                out.extend(tokens[i:fim])
                i = fim
                continue
            numero = _formatar(valor, lingua)
            if decimal is not None:
                numero += ("." if lingua == "en" else ",") + decimal
            out.append(numero)
            i = fim
        return "".join(out)
    except Exception:  # noqa: BLE001 — uma legenda nunca pode partir a voz
        return texto


# ── Os números que vão PARA o modelo ────────────────────────────────────
#
# O contrário do de cima. O motor de SQL devolve números crus — «6153185.72»
# — e o Sonic, sem saber em que língua ler um número sem formato, leu-o em
# inglês numa conversa em castelhano. Formatado como se escreve na língua da
# conversa («6.153.185,72 €»), lê-o nessa língua.

#: Um número cru: sem separadores de milhar, com ou sem decimais com ponto.
#: Não apanha datas (2026-08-01), horas (10:30), versões (1.2.3) nem números
#: já formatados (6.153.185,72 / 6,153,185.72).
_NUMERO_CRU = re.compile(r"(?<![\w.,:/-])(\d+)(?:\.(\d+))?(?![\w]|[.,:/-]\d)")

#: Já com moeda ao lado — então é dinheiro, e a moeda passa a «€».
_EURO_ANTES = re.compile(r"(?:€|EUR)\s*$", re.I)
_EURO_DEPOIS = re.compile(r"^\s*(?:€|EUR\b|euros?\b)", re.I)

#: Palavras que fazem de um número com dois decimais um montante.
_DINHEIRO = re.compile(
    r"\b(factur\w*|fatur\w*|ventas?|vendas?|ingres\w*|receitas?|revenue|sales|"
    r"cost\w*|cust\w*|gast\w*|import\w*|pre[cç]\w*|precio\w*|price\w*|amount|"
    r"montante\w*|valor\w*|value|lucro\w*|beneficio\w*|profit\w*|margem|margen|"
    r"margin|ticket|sald\w*|balance|pag\w*|paid|cobr\w*)\b",
    re.I,
)


def _agrupar(inteiro: str, lingua: str) -> str:
    n = int(inteiro)
    if n < 10000:
        return str(n) if not inteiro.startswith("0") else inteiro
    s = f"{n:,}"
    return s if lingua == "en" else s.replace(",", ".")


def numeros_no_formato(texto: str, lingua: str = "es") -> str:
    """«6153185.72» → «6.153.185,72 €» (es/pt) ou «€6,153,185.72» (en).

    * Inteiros com 5+ algarismos ganham separador de milhar; com 4 ficam
      (é um ano, quase sempre — «2026»).
    * Decimais com ponto passam a vírgula em es/pt.
    * Um número é dinheiro se já tiver moeda ao lado (€/EUR/euros) ou se
      tiver dois decimais numa frase que fala de dinheiro. Dinheiro leva
      sempre «€»: os clientes são europeus.

    Nunca rebenta: devolve o texto como veio.
    """
    lingua = (lingua or "es")[:2].lower()
    if not texto or lingua not in ("es", "pt", "en"):
        return texto
    try:
        fala_de_dinheiro = bool(_DINHEIRO.search(texto))
        out: List[str] = []
        pos = 0
        for m in _NUMERO_CRU.finditer(texto):
            inteiro, decimais = m.group(1), m.group(2)
            # «1.250» já pode ser mil duzentos e cinquenta formatado: três
            # decimais num inteiro curto é ambíguo, e fica.
            if decimais is not None and len(decimais) == 3 and len(inteiro) <= 3:
                continue
            if decimais is None and len(inteiro) < 5:
                # Nada a agrupar — só interessa se for dinheiro já marcado.
                antes, depois = texto[: m.start()], texto[m.end() :]
                if not (_EURO_ANTES.search(antes) or _EURO_DEPOIS.match(depois)):
                    continue
            antes, depois = texto[pos : m.start()], texto[m.end() :]
            com_euro_antes = _EURO_ANTES.search(texto[: m.start()])
            com_euro_depois = _EURO_DEPOIS.match(depois)
            dinheiro = bool(com_euro_antes or com_euro_depois) or (
                decimais is not None and len(decimais) == 2 and fala_de_dinheiro
            )
            numero = _agrupar(inteiro, lingua)
            if decimais is not None:
                numero += ("." if lingua == "en" else ",") + decimais
            if com_euro_antes:
                # Tira o «€»/«EUR» de antes: volta a pôr-se no sítio certo.
                antes = antes[: len(antes) - len(com_euro_antes.group(0))]
            out.append(antes)
            if dinheiro:
                numero = f"€{numero}" if lingua == "en" else f"{numero} €"
                fim = m.end()
                if com_euro_depois:
                    fim += len(com_euro_depois.group(0))
                out.append(numero)
                pos = fim
            else:
                out.append(numero)
                pos = m.end()
        out.append(texto[pos:])
        return "".join(out)
    except Exception:  # noqa: BLE001 — o resultado chega ao modelo de qualquer maneira
        return texto
