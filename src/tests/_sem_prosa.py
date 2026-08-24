"""O código de um módulo, sem comentários e sem docstrings.

Existe porque um guarda meu acendeu por causa da **própria explicação** que o
módulo dá sobre o defeito que corrige: a docstring cita `asyncio.run(...)`
para dizer porque NÃO se usa, e o guarda leu a citação como se fosse uma
chamada.

Um guarda que se engana com a sua própria documentação está a ler prosa, não
código. E o remédio óbvio — parar de escrever a explicação — seria trocar a
coisa certa pela coisa fácil.
"""

from __future__ import annotations

import ast
import inspect
from types import ModuleType


def sem_prosa(modulo: ModuleType) -> str:
    """O código do módulo como texto, sem comentários nem docstrings."""
    arvore = ast.parse(inspect.getsource(modulo))
    for no in ast.walk(arvore):
        corpo = getattr(no, "body", None)
        if not isinstance(corpo, list) or not corpo:
            continue
        primeiro = corpo[0]
        if (
            isinstance(primeiro, ast.Expr)
            and isinstance(primeiro.value, ast.Constant)
            and isinstance(primeiro.value.value, str)
        ):
            corpo.pop(0)
    # `ast.unparse` não devolve comentários — eles nem chegam à árvore.
    return ast.unparse(arvore)
