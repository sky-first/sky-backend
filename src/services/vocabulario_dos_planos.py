# -*- coding: utf-8 -*-
"""Os dois vocabulários de planos, e a tradução entre eles.

Há dois nomes para a mesma coisa, e isso não é um acidente que se
corrija com um rename:

* **o registo** (`tenant_registry.tier`) fala em
  `starter / foundation / core / advanced / strategic`. É o
  vocabulário de provisionamento: diz que infraestrutura o cliente
  leva;
* **o catálogo comercial** (`pricing_tiers`) fala em
  `starter / foundation / scale / enterprise`, que são o Sky Start, o
  Sky Core, o Sky Plus e o Sky Max. É o que se vende.

Os dois sobrepõem-se em `starter` e `foundation` — por coincidência — e
divergem em tudo o resto. Essa coincidência é a razão de o problema ter
demorado a aparecer: metade dos clientes funcionava.

── Porque é que isto vive aqui e não no `console.py` ───────────────

Vivia lá, e o ecrã de detalhe do cliente não o via. O resultado: para
qualquer cliente em `core`, `advanced` ou `strategic`, o separador
Settings do Console comparava `"strategic" === "enterprise"`, nenhum
cartão de plano acendia, o botão ficava em «No change» e o selo mostrava
a palavra interna crua. **O seletor de tier estava morto para todos os
clientes grandes** — exactamente aqueles em que mudar de plano importa.

Uma regra de tradução que vive dentro de um ficheiro de rotas só serve
as rotas desse ficheiro. Aqui serve quem precisar, e há um sítio só
para a corrigir.
"""

from __future__ import annotations

# Registo → comercial.
#
# `core` e `advanced` caem os dois em `scale`: comercialmente é o mesmo
# plano, a diferença entre eles é de infraestrutura.
REGISTO_PARA_COMERCIAL: dict[str, str] = {
    "starter": "starter",
    "foundation": "foundation",
    "core": "scale",
    "advanced": "scale",
    "strategic": "enterprise",
}

# Comercial → registo. Não é a inversa exacta: `scale` tem de escolher
# um dos dois, e escolhe o mais baixo. Promover de `core` para
# `advanced` é uma decisão de infraestrutura e não se faz a partir de um
# cartão de preço.
COMERCIAL_PARA_REGISTO: dict[str, str] = {
    "starter": "starter",
    "foundation": "foundation",
    "scale": "core",
    "enterprise": "strategic",
}

# O nome que uma pessoa lê. O selo mostrava `strategic`, que não é um
# produto que exista em lado nenhum — nem no site, nem numa proposta.
NOME_COMERCIAL: dict[str, str] = {
    "starter": "Sky Start",
    "foundation": "Sky Core",
    "scale": "Sky Plus",
    "enterprise": "Sky Max",
}


def comercial_de(tier_do_registo: str | None) -> str | None:
    """O plano comercial de um tier do registo, ou None se desconhecido.

    Devolve `None` em vez de adivinhar: um tier que ninguém mapeou é um
    tier novo que alguém acrescentou sem passar por aqui, e mostrar um
    plano errado é pior do que mostrar nenhum.
    """
    if not tier_do_registo:
        return None
    return REGISTO_PARA_COMERCIAL.get(tier_do_registo)


def nome_de(tier_do_registo: str | None) -> str | None:
    """O nome que se mostra, a partir do tier do registo."""
    comercial = comercial_de(tier_do_registo)
    return NOME_COMERCIAL.get(comercial) if comercial else None


__all__ = [
    "COMERCIAL_PARA_REGISTO",
    "NOME_COMERCIAL",
    "REGISTO_PARA_COMERCIAL",
    "comercial_de",
    "nome_de",
]
