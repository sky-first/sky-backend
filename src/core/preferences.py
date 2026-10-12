"""Fusão das preferências do utilizador.

A web (``PUT /users/me``) e a app (``PUT /settings``) gravam no mesmo
``users.preferences``. A fusão só ao primeiro nível fazia com que um
``{"voice": {"voice": "lupe"}}`` vindo de um aparelho apagasse o
``voice.patience`` gravado pelo outro. Aqui a fusão é em profundidade:

- dicionário sobre dicionário funde chave a chave, recursivamente;
- qualquer outro valor substitui o que lá estava;
- ``None`` apaga a chave (é a forma de um cliente limpar uma preferência).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional


def deep_merge_preferences(
    base: Optional[Mapping[str, Any]], patch: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Devolve um dicionário NOVO com ``patch`` fundido em ``base``.

    Nunca altera ``base`` nem ``patch``: o SQLAlchemy só deteta a mudança
    num JSON quando o objeto é outro (ou com ``flag_modified``), e partilhar
    sub-dicionários com o pedido abria a porta a mutações acidentais.
    """
    resultado: Dict[str, Any] = copy.deepcopy(dict(base or {}))
    for chave, valor in (patch or {}).items():
        if valor is None:
            resultado.pop(chave, None)
        elif isinstance(valor, Mapping) and isinstance(resultado.get(chave), Mapping):
            resultado[chave] = deep_merge_preferences(resultado[chave], valor)
        elif isinstance(valor, Mapping):
            # Não havia dicionário por baixo: limpa os None do que chega.
            resultado[chave] = deep_merge_preferences({}, valor)
        else:
            resultado[chave] = copy.deepcopy(valor)
    return resultado
