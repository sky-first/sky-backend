"""Que tectos se aplicam a cada plano — os quatro, e a sério.

**O defeito, e é dinheiro.** Havia dois registos de planos que não coincidiam:

* ``pricing_tiers.TIER_REGISTRY`` — o que o Console mostrava e vendia:
  starter · foundation · **core** · **advanced** · **strategic**
* ``tenant_plan_limits.TIER_LIMITS`` — o que o sistema **aplicava**:
  starter · foundation · **scale** · **enterprise**

Só ``starter`` e ``foundation`` existiam nos dois. E o código dizia, à letra::

    product tiers that don't exist in TIER_LIMITS are treated as
    enterprise/unlimited — they pre-date the pricing model

Ou seja: um cliente num plano que o Console sabia vender e a tabela não sabia
aplicar **não era limitado em nada**. O plano existia na fatura e não existia
no sistema.

O comentário no modelo dizia «the two will be reconciled in Fase 3». A Fase 3
não aconteceu, e entretanto começou-se a vender.

── Os quatro planos, e de onde vêm os números ───────────────────────────────

Preços fechados pelo Lucas a 24/08/2026: **450 / 950 / 1800 €/mês**, e o
enterprise negociado caso a caso.

Os limites **não são escolhidos à mão** — saem da conta em
:mod:`src.services.economia_dos_planos`, que parte do custo real de uma
pergunta (três chamadas ao modelo: Haiku, Sonnet, Haiku ≈ **0,03 €**) e da
infraestrutura fixa (**1300 €/mês**, independente do número de clientes).

Com estes limites, os três planos pagos chegam aos 80 % de margem por volta
dos **20 clientes** — e é esse o número que decide se o negócio fecha, não o
preço isolado. Com 5 clientes o starter dá 36 %.

── Uma moeda só: a pergunta ─────────────────────────────────────────────────

**Uma corrida de agente é uma pergunta.** Não há diferença técnica nenhuma —
o agente é uma pergunta que se repete sozinha, e custa o mesmo. Contá-las
separadamente convidava a que alguém contornasse o limite de perguntas
criando agentes, que é o caminho mais caro dos dois porque corre sem ninguém
estar a olhar.

── Porque isto não precisa de migração ──────────────────────────────────────

A coluna ``tier`` tem uma restrição na base a quatro valores
(``starter|foundation|scale|enterprise``) — que, felizmente, são agora
exactamente os quatro planos. Os tectos que a aplicação lê são as colunas
numéricas, e essas aceitam qualquer número.

── Um plano desconhecido continua sem tecto, mas já não em silêncio ─────────

A tentação era fechar: plano desconhecido, tectos do mais pequeno. Mau — um
erro de configuração passaria a cortar o serviço a um cliente que paga, e o
primeiro a saber seria ele.

Um plano desconhecido é um **erro de configuração nosso**. Continua a servir,
mas grita. O que não pode voltar a acontecer é ser silencioso.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Rótulo permitido pela restrição da base, por plano. Hoje é a identidade
#: para os quatro — mas os nomes antigos continuam a mapear, para as linhas
#: que já estão gravadas não ficarem órfãs.
ROTULO_APLICADO: Dict[str, str] = {
    "starter": "starter",
    "foundation": "foundation",
    "scale": "scale",
    "enterprise": "enterprise",
    # Nomes do catálogo anterior. Um cliente gravado com um destes continua a
    # ser limitado — antes caía em «ilimitado».
    "core": "scale",
    "advanced": "enterprise",
    "strategic": "enterprise",
    "pilot": "starter",  # nome do starter antes de 30/05
}

#: Os tectos. `None` = sem tecto.
#:
#: `max_queries_per_month` conta as perguntas E as corridas dos agentes — ver
#: a nota no topo. Os valores saem de `economia_dos_planos`.
TECTOS: Dict[str, Dict[str, Optional[int]]] = {
    "starter": {  # Sky Start — 490 €/mês
        "max_agents": 3,
        # A página promete «utilizadores ilimitados». Uma promessa na página é
        # um contrato: cobra-se pelo que se vigia, não por quem olha.
        "max_users": None,
        "max_storage_gb": 50,
        "max_queries_per_month": 500,
    },
    "foundation": {  # Sky Core — 900 €/mês
        "max_agents": 10,
        "max_users": None,
        "max_storage_gb": 200,
        "max_queries_per_month": 2_000,
    },
    "scale": {  # Sky Plus — 1800 €/mês
        "max_agents": 30,
        "max_users": None,
        "max_storage_gb": 500,
        "max_queries_per_month": 8_000,
    },
    "enterprise": {
        # Negociado por contrato, caso a caso. É o único sem tecto.
        "max_agents": None,
        "max_users": None,
        "max_storage_gb": None,
        "max_queries_per_month": None,
    },
}
# Os nomes antigos herdam os tectos do plano para onde apontam.
for _antigo, _novo in (("core", "scale"), ("advanced", "enterprise"),
                       ("strategic", "enterprise"), ("pilot", "starter")):
    TECTOS[_antigo] = dict(TECTOS[_novo])

#: Decisões que eu não podia tomar. Lidas por um teste, para não ficarem
#: esquecidas num comentário que ninguém abre — que foi exactamente o destino
#: da «Fase 2» dos avisos.
A_CONFIRMAR: Dict[str, str] = {
    "armazenamento": (
        "Os GB de cada plano não vieram de nenhuma conta — herdei-os do "
        "catálogo anterior. O custo de armazenamento é pequeno ao pé dos "
        "tokens, mas os números merecem uma olhada."
    ),
    "utilizadores": (
        "Idem. O número de utilizadores não custa tokens directamente, mas "
        "mais gente faz mais perguntas — e essas contam."
    ),
    "medicao_real_dos_tokens": (
        "O custo por pergunta (0,03 €) é uma estimativa da forma dos pedidos, "
        "não uma medição. A medição existe na `tenant_llm_daily_snapshots` "
        "(via Langfuse): com um mês de dados a sério, substituir."
    ),
}


def tectos_de(plano: str) -> Tuple[str, Dict[str, Optional[int]], bool]:
    """`(rótulo a gravar, tectos, é_conhecido)` para um plano.

    Um plano desconhecido devolve sem tecto e `False` — continua a servir, mas
    quem chama tem de o registar. Ver a nota no topo: fechar num erro de
    configuração nosso cortava o serviço a quem paga.
    """
    p = (plano or "").strip().lower()
    if p in TECTOS:
        return ROTULO_APLICADO.get(p, "enterprise"), dict(TECTOS[p]), True

    logger.warning(
        "tectos_do_plano: plano desconhecido %r — a servir SEM TECTO. "
        "Isto é um erro de configuração: ou o plano é novo e falta aqui, ou "
        "o registo do cliente tem um valor que ninguém escreveu.",
        plano,
    )
    return "enterprise", dict(TECTOS["enterprise"]), False
