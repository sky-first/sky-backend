"""Seed realistic demo data for the context layer.

Run this after the DB is up and the owner user exists. It populates
every category that orbits the Universe Intelligence sun with enough
signal that:

  * Every 8 context categories show non-zero counts.
  * The AI chat has actual content to retrieve (strategy, events,
    glossary, relationships).
  * Destructive tests and use cases exercise realistic volumes.

Idempotent: re-running only inserts missing rows (lookups are by
``name``/``term``/``title`` within the target scope).

Usage:
    cd sky-poc-backend
    source venv/bin/activate
    python scripts/seed_context_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Optional

from sqlalchemy import select

from src.config.database import AsyncSessionLocal
from src.models.enterprise_relationship import EnterpriseRelationship
from src.models.glossary import GlossaryTerm
from src.models.space import Space
# Strategy seed removed in the Knowledge refactor (2026-04-25). The
# Metric-based seed lands in Phase 2 — see KNOWLEDGE_REFACTOR.md.
from src.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_context_demo")


# ─── Dictionaries of realistic demo content ──────────────────────────────

GLOSSARY_TERMS = [
    ("GMV", "Gross Merchandise Value — soma bruta do valor de todos os pedidos colocados na plataforma em um período."),
    ("ARR", "Annual Recurring Revenue — receita recorrente anualizada das assinaturas ativas."),
    ("MRR", "Monthly Recurring Revenue — receita recorrente mensal das assinaturas ativas."),
    ("CAC", "Customer Acquisition Cost — custo médio gasto para adquirir um novo cliente pagante."),
    ("LTV", "Lifetime Value — receita total esperada de um cliente ao longo de todo o ciclo de vida."),
    ("Churn", "Taxa mensal de cancelamento de clientes sobre a base ativa do período anterior."),
    ("MAU", "Monthly Active Users — usuários únicos que executaram ao menos uma ação no período de 30 dias."),
    ("NPS", "Net Promoter Score — índice de recomendação líquida medido por pesquisa periódica de satisfação."),
    ("Runway", "Meses de operação restantes ao ritmo atual de caima de caixa, dado o saldo disponível."),
    ("Payback period", "Tempo médio necessário para recuperar o custo de aquisição de um cliente via receita."),
    ("TAM", "Total Addressable Market — tamanho total do mercado acessível para o produto."),
    ("SAM", "Serviceable Addressable Market — fatia do TAM que efetivamente pode ser atendida."),
    ("SOM", "Serviceable Obtainable Market — parcela do SAM capturável em 12 meses dado canal e capacidade."),
    ("OKR", "Objectives and Key Results — framework de metas com objetivo qualitativo e resultados mensuráveis."),
    ("Pillar", "Direção estratégica plurianual que agrupa objetivos e iniciativas relacionadas."),
]


PILLARS = [
    ("Experiência do Cliente", "Elevar satisfação e retenção via jornada fluida e suporte proativo.", "#8b5cf6"),
    ("Eficiência Operacional", "Reduzir custos unitários e aumentar throughput sem prejuízo de qualidade.", "#10b981"),
    ("Expansão de Receita", "Acelerar aquisição em novos segmentos e upsell dentro da base atual.", "#f59e0b"),
    ("Inovação de Produto", "Lançar 2 produtos novos com adoção ≥ 20% da base em 12 meses.", "#3b82f6"),
]


OBJECTIVES = [
    ("corporate", "Aumentar ARR em 30% até Q4/2026", "Crescer receita recorrente via novos contratos e upsell.", "on_track", "high", "Revenue"),
    ("corporate", "Reduzir churn mensal para < 2%", "Churn mensal nos últimos 3 meses foi 3.1%; meta é 2%.", "at_risk", "critical", "Retention"),
    ("unit", "Elevar NPS corporate de 42 para 60", "Programa de customer success proativo + melhoria de SLA.", "on_track", "medium", "CX"),
    ("team", "Lançar onboarding self-service v2", "Reduzir tempo até primeiro valor (TTV) de 14 para 5 dias.", "lagging", "high", "Product"),
    ("team", "Implantar pipeline CI/CD unificada", "Consolidar 3 pipelines legadas em 1 com trace distribuído.", "on_track", "medium", "Eng"),
]


OKR_TITLES = [
    ("ARR Q2: expansão enterprise", 2_400_000.0, 3_100_000.0, "USD", "quarterly"),
    ("Churn mensal ≤ 2% até Jun/2026", 3.1, 2.0, "%", "monthly"),
    ("NPS corporate ≥ 60", 42.0, 60.0, "pts", "quarterly"),
    ("TTV novos clientes ≤ 5 dias", 14.0, 5.0, "days", "monthly"),
]


KEY_RESULTS = [
    ("Fechar 12 contratos enterprise (ACV ≥ 50k)", 0.0, 12.0, 4.0, "contracts"),
    ("Reduzir churn voluntário em 1.1pp", 3.1, 2.0, 2.7, "%"),
    ("Reduzir tempo de resposta de suporte para < 4h", 9.0, 4.0, 6.0, "hours"),
    ("95% dos novos clientes ativam em ≤ 5 dias", 42.0, 95.0, 61.0, "%"),
]


INITIATIVES = [
    ("Playbook CS proativo por tier", "Segmentar base por tier e criar playbook por segmento.", "active"),
    ("Automação de cobrança recorrente", "Reduzir falhas de pagamento em 40% com retry inteligente.", "active"),
    ("Programa de referral empresarial", "Incentivo duplo para referrals Enterprise fechados em 90 dias.", "planned"),
    ("Redesenho do onboarding self-service", "Fluxo guiado em 4 etapas com telemetria.", "active"),
]


RISKS = [
    ("Dependência de 1 provedor de pagamento", "Risco de indisponibilidade caso único PSP falhe por > 1h.", "infrastructure", 4, 3),
    ("Concentração de receita em 5 contas", "Top-5 contas representam 38% do ARR.", "commercial", 5, 3),
    ("Gap de perfis seniores em dados", "Fila de ramp-up em Eng-Data pode atrasar projetos de Q3.", "people", 4, 4),
    ("Compliance LGPD para novos produtos", "Novos flows podem exigir DPIA antes do lançamento.", "legal", 3, 3),
]


# EVENTS list and seed_events() removed in Phase 1b alongside the
# SignalEvent model. Phase 2 brings agent-emitted findings back via the
# Pulse halo + Universe Intelligence — wired through agent_findings,
# not a dedicated events table.


RELATIONSHIPS = [
    ("ARR", "GMV", "derives_from", "ARR é uma projeção linear de 12× MRR atualizado."),
    ("MRR", "Churn", "affected_by", "Churn mensal reduz base que compõe MRR no mês seguinte."),
    ("LTV", "CAC", "ratio", "Saúde unit economics: LTV/CAC ≥ 3× é alvo saudável."),
    ("Deploy failure", "Churn", "risk_contributor", "Incidentes de produção correlacionam com churn 90d."),
    ("NPS", "Retention", "leading_indicator", "Movimento do NPS antecipa variação de retenção em 1 trimestre."),
]


# ─── Helper upsert routines ───────────────────────────────────────────────


async def get_owner_user(session) -> Optional[User]:
    stmt = select(User).where(User.role == "owner").limit(1)
    r = await session.execute(stmt)
    u = r.scalar_one_or_none()
    if u:
        return u
    stmt = select(User).where(User.role == "admin").limit(1)
    r = await session.execute(stmt)
    return r.scalar_one_or_none()


async def get_first_space(session) -> Optional[Space]:
    r = await session.execute(select(Space).limit(1))
    return r.scalar_one_or_none()


async def seed_glossary(session, space_id, owner_id):
    logger.info("Seeding glossary terms …")
    added = 0
    for term, definition in GLOSSARY_TERMS:
        stmt = select(GlossaryTerm).where(
            GlossaryTerm.term == term,
            GlossaryTerm.space_id == space_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            continue
        session.add(
            GlossaryTerm(
                term=term,
                definition=definition,
                space_id=space_id,
                owner_user_id=owner_id,
            )
        )
        added += 1
    logger.info("  %d new terms added", added)


# seed_strategy() was removed when the Strategy module was dropped in
# the Knowledge refactor (2026-04-25). PILLARS / OBJECTIVES / OKR_TITLES /
# KEY_RESULTS / INITIATIVES / RISKS data above is kept as a reference for
# the Phase 2 Metric/tag seed that replaces this function.


async def seed_relationships(session):
    logger.info("Seeding enterprise relationships …")
    added = 0
    for src, dst, rel_type, desc in RELATIONSHIPS:
        # EnterpriseRelationship fields vary; use a forgiving kwargs approach.
        stmt = select(EnterpriseRelationship).where(EnterpriseRelationship.name == f"{src} → {dst}")
        try:
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                continue
        except Exception:
            # model may not expose `name` — fall through to insert
            existing = None
        try:
            session.add(
                EnterpriseRelationship(
                    name=f"{src} → {dst}",
                    description=desc,
                    relationship_type=rel_type,
                )
            )
            added += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("  could not insert relationship %s→%s: %s", src, dst, e)
    logger.info("  %d new relationships added", added)


async def main():
    async with AsyncSessionLocal() as session:
        owner = await get_owner_user(session)
        space = await get_first_space(session)
        if not owner:
            logger.error("No owner/admin user found. Create one first.")
            sys.exit(1)
        if not space:
            logger.error("No Space found. Create one first (or rerun bootstrap).")
            sys.exit(1)
        logger.info("Seeding into space=%s owner=%s", space.name, owner.email)
        await seed_glossary(session, space.id, owner.id)
        # Strategy seed removed in Phase 1a; Events seed removed in Phase 1b.
        # Both reappear in Phase 2 as Metric + agent_findings seeds.
        await seed_relationships(session)
        await session.commit()
        logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
