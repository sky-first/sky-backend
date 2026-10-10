# -*- coding: utf-8 -*-
"""Uma pergunta falada leva ponto de interrogação — e «¿» em castelhano.

> «ele não coloca ainda o ponto de interrogação, quando é uma pergunta… isso
>  aí é mandatório» — Lucas, 10/10

A transcrição do Sonic vem às vezes com «?», nunca com «¿», e às vezes sem
nada. Decide-se pelas palavras interrogativas do início, como faria quem
ouve. A app tem a mesma regra (`src/voice/pontuacao.ts`) para o ecrã de voz
e o fio dizerem a mesma coisa — se mudares uma, muda a outra.
"""
from __future__ import annotations

import re

# Só palavras que, a abrir a frase, quase nunca são outra coisa. «Tenho»,
# «hay» ou «que» ficaram de fora: «Tenho uma reunião» não é pergunta, e um
# «?» errado lê-se pior do que um que falta.
INTERROGATIVAS = (
    # PT
    "quanto",
    "quanta",
    "quantos",
    "quantas",
    "qual",
    "quais",
    "quando",
    "onde",
    "aonde",
    "como",
    "quem",
    "porque",
    "porquê",
    "por que",
    "o que",
    "o quê",
    "será que",
    "podes",
    "pode",
    "consegues",
    # ES (com e sem acento: o reconhecimento às vezes tira-o)
    "cuánto",
    "cuánta",
    "cuántos",
    "cuántas",
    "cuanto",
    "cuanta",
    "cuantos",
    "cuantas",
    "cuál",
    "cuáles",
    "cuándo",
    "dónde",
    "adónde",
    "cómo",
    "quién",
    "quiénes",
    "por qué",
    "qué",
    "puedes",
    "podrías",
    "sabes",
    # EN
    "how",
    "what",
    "which",
    "when",
    "where",
    "who",
    "whom",
    "whose",
    "why",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
)


#: Palavras que só existem (ou quase) em castelhano. Decidem o «¿» pelo
#: TEXTO, e não pela língua da sessão.
_SO_CASTELHANO = frozenset(
    """
    cuánto cuánta cuántos cuántas cuanto cuanta cuantos cuantas cuál cuáles
    cual cuales cuándo cuando dónde donde adónde cómo qué quién quiénes hay
    tengo tenemos tienes tiene tienen tengo hemos he has puedo puedes podrías
    podemos sabes yo usted ustedes nosotros mi mis el los las del y muy hoy
    ayer mes año años ventas facturado facturamos facturación tiendas
    personas están estoy
    """.split()
)
#: E as que só existem (ou quase) em português.
_SO_PORTUGUES = frozenset(
    """
    quanto quanta quantos quantas qual quais quando onde aonde quem você
    vocês eu tenho temos tem têm tens não são há hoje ontem meu minha meus
    minhas nós os dos das na nas foi é estou estão faturado
    faturação faturamos vendas lojas pessoas mês ano anos
    """.split()
)

#: E as inglesas: «how many stores» numa sessão em castelhano não leva «¿».
_SO_INGLES = frozenset(
    """
    how what which when where who whom whose why many much do does did we
    you i have has is are the our my stores customers sales revenue
    """.split()
)


def e_castelhano(texto: str) -> bool | None:
    """O texto é castelhano? `None` se não der para dizer.

    > «¿Quantos clientes eu tenho?» — Lucas, 10/10: uma pergunta em
    > português com o «¿» do castelhano, porque a SESSÃO era em espanhol.

    Conta as palavras que só uma das línguas tem. «ñ» é castelhano; «ão»,
    «ões» e «ç» são português.
    """
    t = (texto or "").lower()
    palavras = re.findall(r"[^\W\d_]+", t)
    es = sum(1 for p in palavras if p in _SO_CASTELHANO) + t.count("ñ")
    pt = sum(1 for p in palavras if p in _SO_PORTUGUES) + len(re.findall(r"ões|ão|ç|ã|õ|lh|nh", t))
    en = sum(1 for p in palavras if p in _SO_INGLES)
    if en > max(es, pt):
        return False
    if es > pt:
        return True
    if pt > es:
        return False
    return None


def e_uma_pergunta(texto: str) -> bool:
    # Sem tirar acentos: «qué» pergunta, «que» quase nunca.
    t = re.sub(r"^[¿¡\"'«\s]+", "", (texto or "").strip()).lower()
    if not t:
        return False
    return any(t == p or t.startswith(p + " ") or t.startswith(p + ",") for p in INTERROGATIVAS)


def pontuar_pergunta(texto: str, lingua: str = "") -> str:
    """Maiúscula no início e, se for pergunta, «?» no fim (e «¿» se o texto for castelhano)."""
    t = (texto or "").strip()
    if not t:
        return t
    if e_uma_pergunta(t):
        t = re.sub(r"[.!…]+$", "", t)
        if not t.endswith("?"):
            t += "?"
        # O «¿» decide-o o TEXTO. Só quando o texto não diz (palavras que as
        # duas línguas partilham: «como estás») é que vale a da sessão.
        castelhano = e_castelhano(t)
        if castelhano is None:
            castelhano = (lingua or "").lower().startswith("es")
        if castelhano and not t.startswith("¿"):
            t = "¿" + t
        elif not castelhano and t.startswith("¿"):
            # Um «¿» que já vinha (de um servidor antigo, ou do próprio
            # reconhecimento) numa pergunta que não é castelhana sai.
            t = t[1:].lstrip()
    m = re.match(r"^(¿?)(.)", t)
    if m and m.group(2).islower():
        t = m.group(1) + m.group(2).upper() + t[m.end() :]
    return t
