"""Quanto custa uma pergunta, e quantas cabem em cada plano.

Os limites dos planos não podem ser números escolhidos à mão: são a diferença
entre vender com margem e vender a perder. Este módulo é a conta, escrita de
forma a poder ser discutida — e corrigida — em vez de estar espalhada por uma
folha de cálculo que ninguém encontra.

── O que custa dinheiro numa pergunta ───────────────────────────────────────

Uma pergunta à Sky passa por três chamadas ao modelo (ver o `sky-ai`):

1. **Orquestrador** (Haiku) — escolhe as tabelas. Recebe a pergunta, o
   contexto do RAG e as descrições das tabelas candidatas.
2. **Especialista** (Sonnet) — escreve o SQL e executa-o. É o caro: escrever
   SQL certo é onde a qualidade do modelo se nota, e por isso é Sonnet.
3. **Formatador** (Haiku) — escreve a resposta em português. Recebe a
   pergunta, uma amostra dos dados e as estatísticas.

**Uma corrida de agente é uma pergunta.** Não há diferença técnica: o agente é
uma pergunta que se repete sozinha. É por isso que os limites contam as duas
na mesma moeda — separá-las convidava a que alguém contornasse o limite de
perguntas criando agentes.

── Porque isto é uma ESTIMATIVA, e como se corrige ──────────────────────────

Os tamanhos abaixo são a nossa melhor leitura da forma dos pedidos, não uma
medição. A medição real existe e está por cliente e por dia na
`tenant_llm_daily_snapshots` (alimentada pelo Langfuse) — assim que houver um
mês de dados a sério, os valores daqui devem ser substituídos pelos medidos,
e o `custo_por_pergunta_eur` deixa de ser um palpite informado.

Até lá, **os números pecam por excesso de propósito**: uma estimativa
optimista aqui é uma margem que não existe na fatura.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# ── Preços do Bedrock, por milhão de tokens, em USD ──────────────────────
#
# Família Claude 4.5 em eu-west-1, que é onde o `sky-ai` corre. Se a AWS
# mudar os preços, é aqui que se mexe.
PRECO_HAIKU_ENTRADA = 1.00
PRECO_HAIKU_SAIDA = 5.00
PRECO_SONNET_ENTRADA = 3.00
PRECO_SONNET_SAIDA = 15.00

#: Câmbio para euros. Conservador de propósito — ver a nota no topo.
USD_PARA_EUR = 0.95


@dataclass(frozen=True)
class FormaDoPedido:
    """Quantos tokens cada passo consome, em média."""

    orquestrador_entrada: int = 6_000
    orquestrador_saida: int = 250
    especialista_entrada: int = 4_500
    especialista_saida: int = 350
    formatador_entrada: int = 3_500
    formatador_saida: int = 350


FORMA = FormaDoPedido()


def custo_por_pergunta_usd(forma: FormaDoPedido = FORMA) -> float:
    """O custo de UMA pergunta, do princípio ao fim."""
    haiku_entrada = forma.orquestrador_entrada + forma.formatador_entrada
    haiku_saida = forma.orquestrador_saida + forma.formatador_saida
    return (
        haiku_entrada / 1_000_000 * PRECO_HAIKU_ENTRADA
        + haiku_saida / 1_000_000 * PRECO_HAIKU_SAIDA
        + forma.especialista_entrada / 1_000_000 * PRECO_SONNET_ENTRADA
        + forma.especialista_saida / 1_000_000 * PRECO_SONNET_SAIDA
    )


def custo_por_pergunta_eur(forma: FormaDoPedido = FORMA) -> float:
    return custo_por_pergunta_usd(forma) * USD_PARA_EUR


#: O que a plataforma inteira custa por mês, independentemente do número de
#: clientes: EKS, RDS, Redis, balanceadores, ECR. Medido a 24/08/2026.
#:
#: **Este é o número que decide se a margem existe.** Com poucos clientes ele
#: domina tudo: a €450 com 80% de margem sobram €90 de custo por cliente, e
#: €1300 divididos por 5 clientes já são €260 — o dobro do que há.
INFRA_MENSAL_EUR = 1_300.0


@dataclass(frozen=True)
class Plano:
    slug: str
    nome: str
    preco_mensal_eur: Optional[int]  # None = negociado
    agentes: Optional[int]
    perguntas_por_mes: Optional[int]
    ligacoes: Optional[int]
    utilizadores: Optional[int]


#: Os quatro planos. Preços fechados pelo Lucas a 24/08/2026.
#:
#: As perguntas incluem as corridas dos agentes — ver a nota no topo.
PLANOS: Dict[str, Plano] = {
    "starter": Plano("starter", "Starter", 450, 3, 1_000, 3, 5),
    "foundation": Plano("foundation", "Foundation", 950, 10, 4_000, 10, 25),
    "scale": Plano("scale", "Scale", 1_800, 30, 10_000, 25, 100),
    # Negociado caso a caso. Sem tectos na plataforma: o contrato é que manda.
    "enterprise": Plano("enterprise", "Enterprise", None, None, None, None, None),
}


def custo_de_tokens_no_limite_eur(slug: str) -> float:
    """Quanto custam os tokens se o cliente gastar o plano TODO.

    É o pior caso, e é o que interessa: uma margem que só existe enquanto o
    cliente não usa o que pagou não é uma margem, é sorte.
    """
    p = PLANOS[slug]
    if p.perguntas_por_mes is None:
        return 0.0
    return p.perguntas_por_mes * custo_por_pergunta_eur()


def margem(slug: str, clientes_a_dividir_a_infra: int) -> Dict[str, float]:
    """A margem deste plano, com a infra dividida por N clientes.

    `clientes_a_dividir_a_infra` não é um detalhe: é a variável que decide se
    o negócio fecha. Ver `INFRA_MENSAL_EUR`.
    """
    p = PLANOS[slug]
    if p.preco_mensal_eur is None:
        return {}
    tokens = custo_de_tokens_no_limite_eur(slug)
    infra = INFRA_MENSAL_EUR / max(1, clientes_a_dividir_a_infra)
    custo = tokens + infra
    lucro = p.preco_mensal_eur - custo
    return {
        "preco": float(p.preco_mensal_eur),
        "tokens": round(tokens, 2),
        "infra": round(infra, 2),
        "custo": round(custo, 2),
        "lucro": round(lucro, 2),
        "margem_pct": round(lucro / p.preco_mensal_eur * 100, 1),
    }


def clientes_para_margem(slug: str, alvo_pct: float = 80.0) -> Optional[int]:
    """Quantos clientes são precisos para este plano dar `alvo_pct` de margem.

    Devolve `None` quando nem com infinitos clientes se lá chega — ou seja,
    quando só os tokens já comem mais do que a margem permite. É o sinal de
    que o limite de perguntas está alto de mais para o preço.
    """
    p = PLANOS[slug]
    if p.preco_mensal_eur is None:
        return None
    custo_maximo = p.preco_mensal_eur * (1 - alvo_pct / 100)
    tokens = custo_de_tokens_no_limite_eur(slug)
    sobra_para_infra = custo_maximo - tokens
    if sobra_para_infra <= 0:
        return None
    import math

    return math.ceil(INFRA_MENSAL_EUR / sobra_para_infra)
