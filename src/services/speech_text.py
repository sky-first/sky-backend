"""O mesmo texto, preparado para ser DITO em voz alta.

A resposta do modelo vem em markdown e ia crua para a síntese de voz. O que
o utilizador ouvia era a Sky a ler a marcação: os asteriscos do negrito, os
hífenes das listas, os cardinais dos títulos.

No cliente isto já foi corrigido (`apps/mobile/src/components/markdownParse.ts`,
`speechText`), mas essa correcção só protege o caminho LOCAL, que é o da web.
**Num telemóvel quem sintetiza é o servidor** — este ficheiro — e por isso o
defeito continuava a ouvir-se exactamente onde foi reportado.

As quebras de linha ficam de propósito. Colapsar tudo numa linha faz o motor
ler uma lista de seis números de enfiada, sem respirar; cada item continua a
ser uma frase.
"""

from __future__ import annotations

import re

#: Um bloco de código não se lê em voz alta — seriam minutos de sintaxe.
_BLOCO_CODIGO = re.compile(r"```.*?```", re.DOTALL)
_CODIGO_INLINE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_NEGRITO = re.compile(r"\*\*([^*]+)\*\*")
_ITALICO = re.compile(r"(^|\s)\*([^*]+)\*")
_TITULO = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MARCADOR = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_CITACAO = re.compile(r"^\s*>\s?", re.MULTILINE)
#: Espaços dentro da linha, sem tocar nas quebras.
_ESPACOS = re.compile(r"[^\S\n]+")
_ESPACOS_NA_QUEBRA = re.compile(r"[^\S\n]*\n[^\S\n]*")
_QUEBRAS_A_MAIS = re.compile(r"\n{3,}")


def speech_text(md: str | None) -> str:
    """Devolve `md` sem marcação, pronto para a síntese de voz.

    Espelha o `speechText` da app, incluindo o critério das quebras de linha.
    Se um dos dois mudar, o outro tem de mudar — senão a mesma resposta soa
    diferente conforme o caminho, que é o género de divergência que ninguém
    descobre até um cliente a ouvir.
    """
    if not md:
        return ""
    t = _BLOCO_CODIGO.sub(" ", md)
    t = _CODIGO_INLINE.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _NEGRITO.sub(r"\1", t)
    t = _ITALICO.sub(r"\1\2", t)
    t = _TITULO.sub("", t)
    t = _MARCADOR.sub("", t)
    t = _CITACAO.sub("", t)
    t = _ESPACOS.sub(" ", t)
    t = _ESPACOS_NA_QUEBRA.sub("\n", t)
    t = _QUEBRAS_A_MAIS.sub("\n\n", t)
    return t.strip()
