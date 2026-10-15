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


_MESES_DITOS = {
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
    "janeiro",
    "fevereiro",
    "março",
    "maio",
    "junho",
    "julho",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
}


def _antes_de_mes(tokens: List[str], k: int) -> bool:
    """`tokens[k:]` começa por «de <mês>»?"""
    if k >= len(tokens) or tokens[k].lower() != "de":
        return False
    j = _saltar_espacos(tokens, k + 1)
    return j < len(tokens) and tokens[j].lower() in _MESES_DITOS


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
            # Um código dito dígito a dígito a começar por zero («cero uno»,
            # «zero um») volta a «01» — é como `por_extenso` diz a «Tienda 01».
            if tokens[i].lower() in ("cero", "zero"):
                digitos, j = "0", i + 1
                while True:
                    k = _saltar_espacos(tokens, j)
                    if k >= len(tokens) or tokens[k].isspace():
                        break
                    v = _UNIDADES[lingua].get(tokens[k].lower())
                    if v is None or v >= 10 or tokens[k].lower() in ("un", "una", "uma"):
                        break
                    digitos += str(v)
                    j = k + 1
                if len(digitos) > 1:
                    out.append(digitos)
                    i = j
                    continue
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
            # «uno de agosto» → «1 de agosto»: antes de um mês é um dia.
            dia = _antes_de_mes(tokens, k)
            if palavras == 1 and valor < 10 and decimal is None and not (percentagem or dia):
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


# ── Os números que vão para o modelo, JÁ POR EXTENSO (16/10) ────────────
#
# > «a voz fala em espanhol mas diz os números em inglês» — Lucas, 16/10
#
# Com a lupe/carlos (es-US nativas) um «563.919,19 €» lia-se em castelhano.
# A tiffany e o matthew são poliglotas de base inglesa: o modelo, ao gerar a
# fala, passava os algarismos a palavras em INGLÊS («five hundred sixty three
# thousand…») a meio de uma frase em castelhano. A instrução de sistema já o
# proibia e não chegava. O que chega é não lhe dar algarismos para ler: o
# resultado da ferramenta vai com os números já escritos com letras, na
# língua da conversa, e ele lê palavras.
#
# A legenda não muda: o que o Sonic diz volta a algarismos em `em_algarismos`
# (o mesmo «coma»/«vírgula», «por ciento»/«por cento», «euros»).
#
# Só es e pt. Em inglês o modelo lê os algarismos em inglês, que é o certo.

_ES_0_29 = (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
    "catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno "
    "veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete "
    "veintiocho veintinueve"
).split()
_ES_DEZ = {
    3: "treinta",
    4: "cuarenta",
    5: "cincuenta",
    6: "sesenta",
    7: "setenta",
    8: "ochenta",
    9: "noventa",
}
_ES_CEM = {
    1: "ciento",
    2: "doscientos",
    3: "trescientos",
    4: "cuatrocientos",
    5: "quinientos",
    6: "seiscientos",
    7: "setecientos",
    8: "ochocientos",
    9: "novecientos",
}

_PT_0_19 = (
    "zero um dois três quatro cinco seis sete oito nove dez onze doze treze "
    "catorze quinze dezasseis dezassete dezoito dezanove"
).split()
_PT_DEZ = {
    2: "vinte",
    3: "trinta",
    4: "quarenta",
    5: "cinquenta",
    6: "sessenta",
    7: "setenta",
    8: "oitenta",
    9: "noventa",
}
_PT_CEM = {
    1: "cento",
    2: "duzentos",
    3: "trezentos",
    4: "quatrocentos",
    5: "quinhentos",
    6: "seiscentos",
    7: "setecentos",
    8: "oitocentos",
    9: "novecentos",
}


def _es_ate_mil(n: int, fem: bool, apocope: bool) -> str:
    """0 < n < 1000. `apocope`: «un»/«veintiún» (antes de «mil» ou de um nome)."""
    c, r = divmod(n, 100)
    partes = []
    if c:
        if c == 1 and r == 0:
            partes.append("cien")
        else:
            cem = _ES_CEM[c]
            partes.append(cem[:-2] + "as" if fem and c > 1 else cem)
    if r:
        if r < 30:
            p = _ES_0_29[r]
        else:
            d, u = divmod(r, 10)
            p = _ES_DEZ[d] + (f" y {_ES_0_29[u]}" if u else "")
        if p.endswith("uno"):
            if fem:
                p = p[:-1] + "a"
            elif apocope:
                p = p[:-3] + "ún" if p.endswith("tiuno") else p[:-1]
        partes.append(p)
    return " ".join(partes)


def _es_inteiro(n: int, fem: bool = False, apocope: bool = False) -> str:
    if n == 0:
        return "cero"
    mi, resto = divmod(n, 10**6)
    k, u = divmod(resto, 1000)
    partes = []
    if mi:
        # «mil quinientos millones»: os milhões são um número como outro.
        partes.append("un millón" if mi == 1 else _es_inteiro(mi, False, True) + " millones")
    if k:
        # «veintiún mil», mas «doscientas mil personas»: o milhar concorda.
        partes.append("mil" if k == 1 else _es_ate_mil(k, fem, True) + " mil")
    if u:
        partes.append(_es_ate_mil(u, fem, apocope))
    return " ".join(partes)


def _pt_ate_mil(n: int, fem: bool) -> str:
    c, r = divmod(n, 100)
    partes = []
    if c:
        if c == 1 and r == 0:
            partes.append("cem")
        else:
            cem = _PT_CEM[c]
            partes.append(cem[:-2] + "as" if fem and c > 1 else cem)
    if r:
        if r < 20:
            p = _PT_0_19[r]
        else:
            d, u = divmod(r, 10)
            p = _PT_DEZ[d] + (f" e {_PT_0_19[u]}" if u else "")
        if fem:
            p = re.sub(r"\bum$", "uma", p)
            p = re.sub(r"\bdois$", "duas", p)
        partes.append(p)
    return " e ".join(partes)


def _pt_inteiro(n: int, fem: bool = False) -> str:
    if n == 0:
        return "zero"
    mi, resto = divmod(n, 10**6)
    k, u = divmod(resto, 1000)
    # (texto, valor do grupo) — o valor decide o «e» de ligação.
    grupos = []
    if mi:
        grupos.append(("um milhão" if mi == 1 else _pt_inteiro(mi) + " milhões", mi))
    if k:
        grupos.append(("mil" if k == 1 else _pt_ate_mil(k, fem) + " mil", k * 1000))
    if u:
        grupos.append((_pt_ate_mil(u, fem), u))
    # «mil e duzentos», «mil e trinta», mas «mil duzentos e trinta».
    saida = grupos[0][0]
    for texto, valor in grupos[1:]:
        # o valor do grupo dentro do seu milhar (u < 1000; k*1000 → k)
        base = valor if valor < 1000 else valor // 1000
        saida += (" e " if base < 100 or base % 100 == 0 else " ") + texto
    return saida


def _inteiro(n: int, lingua: str, fem: bool = False, apocope: bool = False) -> str:
    return _es_inteiro(n, fem, apocope) if lingua == "es" else _pt_inteiro(n, fem)


def _decimais_por_extenso(d: str, lingua: str) -> str:
    # «0,05» → «cero coma cero cinco»: com zero à esquerda, dígito a dígito
    # (é assim que se diz, e é o que `_ler_decimais` sabe juntar outra vez).
    if d.startswith("0") or len(d) > 3:
        return " ".join(_inteiro(int(c), lingua) for c in d)
    return _inteiro(int(d), lingua)


#: Um número já no formato es/pt («563.919,19», «7,3», «12»), com «€» ou
#: «%» opcionais a seguir. As datas e as horas tratam-se antes, à parte.
_NUMERO_FORMATADO = re.compile(
    r"(?<![\w.,:/-])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?![\w]|[.,:/-]\d)" r"(\s*(?:€|%|EUR\b))?",
    re.I,
)

_DATA_DMY = re.compile(r"(?<![\w/.-])(\d{1,2})/(\d{1,2})/(\d{4})(?![\w/])")
_DATA_ISO = re.compile(r"(?<![\w/.-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")
_HORA = re.compile(r"(?<![\w:.,])([01]?\d|2[0-3]):([0-5]\d)(?![\w:])")
_MESES = {
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre "
    "noviembre diciembre".split(),
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro "
    "novembro dezembro".split(),
}

#: Nomes que acabam em -a/-as e são masculinos — sem isto «200 días» virava
#: «doscientas días». Lista curta de propósito: o que aparece em dados.
_MASCULINOS_EM_A = {
    "día",
    "días",
    "dia",
    "dias",
    "problema",
    "problemas",
    "sistema",
    "sistemas",
    "programa",
    "programas",
    "mapa",
    "mapas",
    "tema",
    "temas",
    "idioma",
    "idiomas",
    "planeta",
    "planetas",
    "esquema",
    "esquemas",
}
_PALAVRA_SEGUINTE = re.compile(r"\s+([^\W\d_]+)", re.UNICODE)


def _feminino(seguinte: str) -> bool:
    s = seguinte.lower()
    return s not in _MASCULINOS_EM_A and (s.endswith("a") or s.endswith("as"))


def por_extenso(texto: str, lingua: str = "es") -> str:
    """«facturó 563.919,19 €» → «facturó quinientos sesenta y tres mil
    novecientos diecinueve coma diecinueve euros». Só es e pt; o resto
    (incluindo inglês) volta tal e qual. Nunca rebenta.

    Também as datas («01/08/2026» → «uno de agosto de dos mil veintiséis»),
    as horas e os códigos com zero à esquerda: qualquer algarismo que chegue
    ao modelo pode sair dito em inglês.

    Recebe o texto JÁ passado por `numeros_no_formato`.
    """
    lingua = (lingua or "")[:2].lower()
    if not texto or lingua not in ("es", "pt"):
        return texto
    virgula = "coma" if lingua == "es" else "vírgula"
    pct = "por ciento" if lingua == "es" else "por cento"

    def trocar(m: "re.Match[str]") -> str:
        inteiro, decimais, unidade = m.group(1), m.group(2), (m.group(3) or "")
        # Códigos («Tienda 01», «007»): dígito a dígito. Em algarismos o
        # Sonic dizia «O One» (medido a 16/10).
        if len(inteiro) > 1 and inteiro.startswith("0") and decimais is None and not unidade:
            return " ".join(_inteiro(int(c), lingua) for c in inteiro)
        n = int(inteiro.replace(".", ""))
        if n >= 10**12:
            return m.group(0)
        u = unidade.strip().lower()
        seg = None if (u or decimais is not None) else _PALAVRA_SEGUINTE.match(texto, m.end())
        fem = seg is not None and _feminino(seg.group(1))
        # «un pedido», «veintiún pedidos», «un euro»; sozinho, «uno».
        apocope = decimais is None and (u in ("€", "eur") or seg is not None)
        palavras = _inteiro(n, lingua, fem=fem, apocope=apocope)
        if decimais is not None:
            palavras += f" {virgula} " + _decimais_por_extenso(decimais, lingua)
        if u in ("€", "eur"):
            if decimais is None and n >= 10**6 and n % 10**6 == 0:
                palavras += " de"  # «un millón de euros»
            palavras += " euro" if (n == 1 and decimais is None) else " euros"
        elif u == "%":
            palavras += f" {pct}"
        elif seg is not None and n >= 10**6 and n % 10**6 == 0:
            palavras += " de"  # «dos millones de pedidos»
        return palavras

    def data(dia: str, mes: str, ano: str) -> Optional[str]:
        d, mm, a = int(dia), int(mes), int(ano)
        if not (1 <= d <= 31 and 1 <= mm <= 12 and 1000 <= a <= 2999):
            return None
        de = " de "
        dia_dito = _inteiro(d, lingua)
        return dia_dito + de + _MESES[lingua][mm - 1] + de + _inteiro(a, lingua)

    def data_dmy(m: "re.Match[str]") -> str:
        return data(m.group(1), m.group(2), m.group(3)) or m.group(0)

    def data_iso(m: "re.Match[str]") -> str:
        return data(m.group(3), m.group(2), m.group(1)) or m.group(0)

    def hora(m: "re.Match[str]") -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return m.group(0)
        if mi == 0:
            return _inteiro(h, lingua, fem=True) + (" en punto" if lingua == "es" else " horas")
        return (
            _inteiro(h, lingua, fem=True)
            + (" y " if lingua == "es" else " e ")
            + _inteiro(mi, lingua)
        )

    try:
        # Datas e horas primeiro: depois de passar pelo de baixo, um
        # «01/08/2026» já não se reconhecia.
        texto = _DATA_DMY.sub(data_dmy, texto)
        texto = _DATA_ISO.sub(data_iso, texto)
        texto = _HORA.sub(hora, texto)
        return _NUMERO_FORMATADO.sub(trocar, texto)
    except Exception:  # noqa: BLE001 — o resultado chega ao modelo de qualquer maneira
        return texto
