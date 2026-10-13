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


# ─── Regras da conta (paridade web ↔ app, 13/10/2026) ───────────────────

#: Os únicos temas que a conta guarda. «Sistema» (seguir o aparelho) é uma
#: escolha de CADA aparelho: o telemóvel escuro à noite não pode pôr a web do
#: escritório às escuras. A web já não o gravava; a app gravava-o e aplicava-o
#: vindo da conta — a mesma conta via regras opostas.
TEMAS_DA_CONTA = ("light", "dark")

#: «Segue a sua pergunta». A omissão quando a conta nunca escolheu a língua
#: das respostas — a app já marcava isto; a web marcava a língua da
#: interface, e a mesma pergunta vinha em línguas diferentes conforme o
#: aparelho.
RESPOSTA_SEGUE_A_PERGUNTA = "auto"


def tema_valido(valor: Any) -> bool:
    return isinstance(valor, str) and valor.strip().lower() in TEMAS_DA_CONTA


def sem_tema_do_aparelho(patch: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """O pedido de escrita, sem um ``theme`` que a conta não guarda.

    ``"system"`` (ou outro valor qualquer) é **ignorado**: fica o claro/escuro
    que lá estava, que é o que os outros aparelhos continuam a mostrar.
    ``None`` continua a apagar a chave.
    """
    limpo: Dict[str, Any] = dict(patch or {})
    if "theme" in limpo and limpo["theme"] is not None:
        if tema_valido(limpo["theme"]):
            limpo["theme"] = limpo["theme"].strip().lower()
        else:
            limpo.pop("theme")
    return limpo


def preferencias_para_ler(prefs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """O que os clientes recebem em ``preferences`` (cópia; não toca na base).

    - ``answer_language`` vazio ou ausente → ``"auto"``;
    - um ``theme`` antigo que não é claro/escuro (``"system"`` gravado pela
      app antes desta regra) não sai.
    """
    lidas: Dict[str, Any] = copy.deepcopy(dict(prefs or {}))
    if not str(lidas.get("answer_language") or "").strip():
        lidas["answer_language"] = RESPOSTA_SEGUE_A_PERGUNTA
    if "theme" in lidas and not tema_valido(lidas["theme"]):
        lidas.pop("theme")
    return lidas


def sanear_ao_gravar(prefs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """O dicionário final a gravar: tira um ``theme`` inválido que já lá
    estivesse (legado), para a base deixar de o ter."""
    final: Dict[str, Any] = dict(prefs or {})
    if "theme" in final and not tema_valido(final["theme"]):
        final.pop("theme")
    return final
