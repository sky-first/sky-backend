"""Os planos da Sky — a ÚNICA tabela.

> «Tudo isso tem que bloquear. Um plano foi estabelecido, tem que ser trocado
> só na consola.» — Lucas, 10/10/2026

Fonte: a proposta comercial oficial (pág. 13), igual para todos os clientes.
Ver `docs/PLANOS_E_LIMITES_2026-10.md` para as decisões, as lacunas e os
testes.

Havia cinco tabelas (`TIER_LIMITS`, `TECTOS`, `TIER_REGISTRY`, `PLANOS`,
`PLAN_QUOTAS`) com nomes e números diferentes. As outras passam a ler daqui.

`None` num tecto quer dizer «sem tecto» e só existe porque a Consola o pôs
assim num cliente Enterprise. Nunca é o valor por omissão de nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

#: As colunas de `tenant_plan_limits` que são tectos, pela ordem do ecrã.
RECURSOS = (
    "max_connections",
    "max_agents",
    "max_queries_per_month",
    "max_storage_gb",
    "min_agent_interval_minutes",
)


@dataclass(frozen=True)
class Plano:
    slug: str
    nome: str
    preco_mensal_eur: Optional[int]
    #: Os tectos, com as chaves de `RECURSOS`.
    tectos: Dict[str, Optional[int]] = field(default_factory=dict)
    seguinte: Optional[str] = None


PLANOS: Dict[str, Plano] = {
    "starter": Plano(
        "starter",
        "Starter",
        490,
        {
            "max_connections": 1,
            "max_agents": 10,
            "max_queries_per_month": 500,
            "max_storage_gb": 10,
            # «Avisos diários»: um agente corre no máximo uma vez por dia.
            "min_agent_interval_minutes": 24 * 60,
        },
        seguinte="core",
    ),
    "core": Plano(
        "core",
        "Core",
        900,
        {
            "max_connections": 2,
            "max_agents": 30,
            "max_queries_per_month": 2_000,
            "max_storage_gb": 50,
            # «Diários e imediatos».
            "min_agent_interval_minutes": 60,
        },
        seguinte="plus",
    ),
    "plus": Plano(
        "plus",
        "Plus",
        1_800,
        {
            "max_connections": 5,
            "max_agents": 100,
            "max_queries_per_month": 8_000,
            "max_storage_gb": 200,
            # «Contínuos».
            "min_agent_interval_minutes": 15,
        },
        seguinte="enterprise",
    ),
    # Negociado por contrato: a Consola escreve os números de cada cliente.
    # Os daqui são o ponto de partida quando se escolhe Enterprise, não um
    # «ilimitado» — ilimitado foi exactamente o defeito de 10/10.
    "enterprise": Plano(
        "enterprise",
        "Enterprise",
        None,
        {
            "max_connections": 10,
            "max_agents": 300,
            "max_queries_per_month": 30_000,
            "max_storage_gb": 500,
            "min_agent_interval_minutes": 5,
        },
        seguinte=None,
    ),
}

#: Nomes que já estão gravados nalgum sítio → o plano de hoje.
ANTIGOS: Dict[str, str] = {
    "pilot": "starter",
    "foundation": "core",
    "scale": "plus",
    "advanced": "enterprise",
    "strategic": "enterprise",
}


def normalizar(slug: Optional[str]) -> Optional[str]:
    """O plano de hoje para um nome qualquer, ou `None` se não se sabe qual."""
    s = (slug or "").strip().lower()
    s = ANTIGOS.get(s, s)
    return s if s in PLANOS else None


def plano(slug: Optional[str]) -> Plano:
    """O plano. Um nome desconhecido é um ERRO — não cai em lado nenhum.

    Antes caía em «enterprise sem tecto», e foi assim que nenhum cliente
    tinha limites. Quem chama decide o que fazer com o erro.
    """
    p = normalizar(slug)
    if p is None:
        raise ValueError(f"plano desconhecido: {slug!r}")
    return PLANOS[p]


def tectos(slug: Optional[str]) -> Dict[str, Optional[int]]:
    return dict(plano(slug).tectos)
