"""Texto de terceiros seguro para ir para os registos.

O corpo de erro do sky-ai pode trazer o SQL gerado, valores de linhas e
mensagens do driver com dados do cliente. Nos registos basta o suficiente
para diagnosticar: a forma do erro, não os valores.
"""

from __future__ import annotations

import re

#: Literais SQL entre plicas, incluindo plicas escapadas ('' ou \').
_LITERAL_ASPAS_SIMPLES = re.compile(r"'(?:[^'\\]|\\.|'')*'")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: Números com 3+ algarismos (NIFs, montantes, ids, telefones).
_NUMERO = re.compile(r"\b\d{3,}(?:[.,]\d+)*\b")

LIMITE_POR_OMISSAO = 300


def texto_para_log(texto: object, limite: int = LIMITE_POR_OMISSAO) -> str:
    """Redige literais, emails e números e corta em ``limite`` caracteres.

    Os valores no SQL vêm entre plicas ('...'): saem. Mantém palavras-chave,
    identificadores e a mensagem do erro — o que serve para perceber o que
    falhou.
    """
    if texto is None:
        return ""
    s = str(texto)
    s = _LITERAL_ASPAS_SIMPLES.sub("'?'", s)
    s = _EMAIL.sub("<email>", s)
    s = _NUMERO.sub("<n>", s)
    s = " ".join(s.split())
    if len(s) > limite:
        s = s[:limite] + f"…(+{len(s) - limite})"
    return s
