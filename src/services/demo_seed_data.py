"""Static demo content seeded into every fresh demo Space.

Lives next to ``DemoService`` so the signup flow can hydrate a new
sandbox with realistic Knowledge content (Glossary, Metrics) plus a
handful of Enterprise Relationships connecting them. Phase 1a (2026-04-25)
collapsed the legacy Strategy module (Pillar / Goal / OKR / Initiative /
Risk / KPI) and the SignalEvent model into the unified ``Metric`` table —
this seed only ships entities that survived that refactor.

Idempotency in the seed routine relies on:
  * ``GlossaryTerm`` — uniqueness on (space_id, term)
  * ``Metric``       — uniqueness on (scope='space', scope_id, slug)
  * ``EnterpriseRelationship`` — name match within (scope, scope_id)
"""

from __future__ import annotations

# 14 baseline terms covering the SaaS/finance/product vocabulary the
# seeded connections (CRM, Marketing, Finance, Web Analytics, Product
# Usage) speak, so the AI can resolve "what's MRR?" / "what's CAC?"
# the moment a visitor lands.
GLOSSARY_TERMS: list[tuple[str, str]] = [
    ("GMV", "Gross Merchandise Value — soma bruta do valor de todos os pedidos colocados na plataforma em um período."),
    ("ARR", "Annual Recurring Revenue — receita recorrente anualizada das assinaturas ativas."),
    ("MRR", "Monthly Recurring Revenue — receita recorrente mensal das assinaturas ativas."),
    ("CAC", "Customer Acquisition Cost — custo médio gasto para adquirir um novo cliente pagante."),
    ("LTV", "Lifetime Value — receita total esperada de um cliente ao longo de todo o ciclo de vida."),
    ("Churn", "Taxa mensal de cancelamento de clientes sobre a base ativa do período anterior."),
    ("MAU", "Monthly Active Users — usuários únicos que executaram ao menos uma ação no período de 30 dias."),
    ("DAU", "Daily Active Users — usuários únicos que executaram ao menos uma ação em 24 horas."),
    ("NPS", "Net Promoter Score — índice de recomendação líquida medido por pesquisa periódica de satisfação."),
    ("Runway", "Meses de operação restantes ao ritmo atual de queima de caixa, dado o saldo disponível."),
    ("Payback period", "Tempo médio necessário para recuperar o custo de aquisição de um cliente via receita."),
    ("TAM", "Total Addressable Market — tamanho total do mercado acessível para o produto."),
    ("SAM", "Serviceable Addressable Market — fatia do TAM que efetivamente pode ser atendida."),
    ("SOM", "Serviceable Obtainable Market — parcela do SAM capturável em 12 meses dado canal e capacidade."),
]


# 10 starter metrics. Description is in PT-BR to match Glossary tone.
# slug is canonical (lower-snake, ASCII) so the per-Space uniqueness
# constraint never fires on punctuation drift. Aggregation/unit follow
# the conventions used by ``Metric.formula_text`` consumers.
METRICS_DATA: list[tuple[str, str, str, str, str]] = [
    # (slug, name, description, unit, aggregation)
    ("mrr", "MRR", "Receita recorrente mensal das assinaturas ativas (proxy de saúde do negócio).", "USD", "sum"),
    ("arr", "ARR", "Receita recorrente anualizada — projeção linear de 12× MRR.", "USD", "sum"),
    ("gmv", "GMV", "Volume bruto de transações no período.", "USD", "sum"),
    ("cac", "CAC", "Custo médio de aquisição de cliente (marketing + sales / novos clientes).", "USD", "avg"),
    ("ltv", "LTV", "Lifetime value médio por cliente nos últimos 12 meses.", "USD", "avg"),
    ("churn_monthly", "Monthly Churn", "Taxa mensal de cancelamento sobre a base ativa do mês anterior.", "%", "avg"),
    ("nps", "NPS", "Net Promoter Score corporativo da pesquisa trimestral.", "pts", "avg"),
    ("mau", "MAU", "Usuários únicos com pelo menos 1 ação nos últimos 30 dias.", "count", "count"),
    ("dau", "DAU", "Usuários únicos com pelo menos 1 ação em 24 horas.", "count", "count"),
    ("payback_period", "Payback Period", "Meses para recuperar o CAC via receita acumulada.", "months", "avg"),
]


# Relationships connect Glossary/Metric concepts so the AI can reason
# across the seeded vocabulary. ``source_term`` and ``target_term``
# match entries above; the seed routine resolves them to the inserted
# Glossary IDs and writes ``sources``/``target_id`` accordingly.
RELATIONSHIPS_DATA: list[tuple[str, str, str, str]] = [
    # (source_term, target_term, relationship_type, description)
    ("ARR", "MRR", "derives_from", "ARR é projeção linear de 12× MRR atualizado."),
    ("MRR", "Churn", "affected_by", "Churn mensal reduz a base que compõe MRR no mês seguinte."),
    ("LTV", "CAC", "ratio", "Saúde unit economics: LTV/CAC ≥ 3× é alvo saudável."),
    ("NPS", "Churn", "leading_indicator", "Movimento do NPS antecipa variação de churn em 1 trimestre."),
    ("Payback period", "CAC", "derives_from", "Payback period mede o tempo para recuperar o CAC via receita."),
    ("DAU", "MAU", "subset_of", "DAU é subconjunto diário do MAU; razão DAU/MAU é proxy de stickiness."),
]
