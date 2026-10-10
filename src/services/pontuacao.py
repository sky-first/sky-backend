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


def e_uma_pergunta(texto: str) -> bool:
    # Sem tirar acentos: «qué» pergunta, «que» quase nunca.
    t = re.sub(r"^[¿¡\"'«\s]+", "", (texto or "").strip()).lower()
    if not t:
        return False
    return any(t == p or t.startswith(p + " ") or t.startswith(p + ",") for p in INTERROGATIVAS)


def pontuar_pergunta(texto: str, lingua: str = "") -> str:
    """Maiúscula no início e, se for pergunta, «?» no fim (e «¿» em castelhano)."""
    t = (texto or "").strip()
    if not t:
        return t
    if e_uma_pergunta(t):
        t = re.sub(r"[.!…]+$", "", t)
        if not t.endswith("?"):
            t += "?"
        if (lingua or "").lower().startswith("es") and not t.startswith("¿"):
            t = "¿" + t
    m = re.match(r"^(¿?)(.)", t)
    if m and m.group(2).islower():
        t = m.group(1) + m.group(2).upper() + t[m.end() :]
    return t
