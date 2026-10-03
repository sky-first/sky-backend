# -*- coding: utf-8 -*-
"""Um pedido sem cliente resolvido não ganha um plano inventado.

── O que aconteceu em produção, a 03/10/2026 ───────────────────────

O painel do plano mostrava a um cliente **«297 de 10 agentes»**, com
*People 0/25* e *Storage 0/50 GB*, e um aviso de «2430% do tecto».

Nenhum dos quatro números era dele:

* o tecto `10 / 25 / 50` vinha de uma linha de `tenant_plan_limits`
  gravada debaixo do sentinela ``UUID(int=0)`` — um cliente que não
  existe. Estava na base da plataforma **e** dentro da base do cliente;
* os 297 eram ``COUNT(*) FROM agents`` na base da **plataforma**, ou
  seja os agentes de toda a gente;
* o cliente tinha 6 agentes, 2 pessoas, e um plano sem limites.

A causa era uma linha de código: quando o `tenant_id` não resolvia,
`get_limits` assumia o plano `foundation` (10 agentes) **e gravava-o**.
A auto-cura existia para cobrir um cliente criado entre migrações; o
que fazia era tornar o engano permanente — a partir da primeira
chamada, a ficção estava na base e já não parecia um erro.

E não era cosmético: `check_can_create_agent` lê o mesmo tecto, logo o
cliente levava **402** ao tentar criar um agente sem ter um único a mais.

Estes testes existem porque o defeito era invisível: tudo respondia 200,
nada aparecia nos registos, e a única pista era um número estranho num
canto do ecrã.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tenant_plan_limits import TenantPlanLimits
from src.services import pricing_service

SEM_CLIENTE = UUID(int=0)


@pytest.mark.asyncio
async def test_nao_grava_nada_para_um_cliente_que_nao_existe(db_session: AsyncSession):
    """É esta a linha que ficou em produção, nos dois sítios."""
    antes = len((await db_session.execute(select(TenantPlanLimits))).scalars().all())

    await pricing_service.get_limits(db_session, tenant_id=SEM_CLIENTE)
    await db_session.flush()

    depois = (await db_session.execute(select(TenantPlanLimits))).scalars().all()
    assert len(depois) == antes, (
        "gravou uma linha de limites para um cliente não resolvido — é assim "
        "que a ficção sobrevive ao pedido"
    )


@pytest.mark.asyncio
async def test_nao_serve_o_tecto_de_10_agentes_a_quem_nao_se_conhece(
    db_session: AsyncSession,
):
    """Assumir o plano mais restrito não é prudente — é errado.

    Um tecto inventado não estraga só um número no ecrã: trava a criação
    de agentes com 402 a quem está dentro do seu plano real.
    """
    row = await pricing_service.get_limits(db_session, tenant_id=SEM_CLIENTE)

    assert row.max_agents is None, (
        f"serviu um tecto de {row.max_agents} agentes a um pedido sem cliente"
    )
    assert row.max_users is None
    assert row.max_storage_gb is None


@pytest.mark.asyncio
async def test_um_cliente_desconhecido_qualquer_recebe_o_mesmo_tratamento(
    db_session: AsyncSession,
):
    """O sentinela não é o único caso.

    Qualquer `tenant_id` que não esteja no registo cai aqui — um cabeçalho
    com um uuid velho, um pedido de um cliente já apagado. Tratar só o
    `UUID(int=0)` deixaria a mesma porta aberta ao lado.
    """
    row = await pricing_service.get_limits(db_session, tenant_id=uuid4())
    assert row.max_agents is None

    await db_session.flush()
    linhas = (await db_session.execute(select(TenantPlanLimits))).scalars().all()
    assert all(r.tenant_id != row.tenant_id for r in linhas) or not linhas


@pytest.mark.asyncio
async def test_um_cliente_conhecido_continua_a_receber_o_plano_dele(
    db_session: AsyncSession,
):
    """O contrapeso: a correcção não pode desligar os limites de todos.

    Sem este caso, devolver «sem limites» a tudo passava os três testes
    acima — e era exactamente o defeito oposto, com o mesmo sintoma
    invisível.
    """
    from datetime import datetime, timezone

    from src.models.tenant_plan_limits import TIER_LIMITS

    tid = uuid4()
    esperada = TenantPlanLimits(
        tenant_id=tid,
        tier="foundation",
        **TIER_LIMITS["foundation"],
        current_agents=0,
        current_users=0,
        current_storage_bytes=0,
        current_queries_this_month=0,
        queries_period_start=datetime.now(timezone.utc),
        last_threshold_alerted={},
    )
    db_session.add(esperada)
    await db_session.flush()

    row = await pricing_service.get_limits(db_session, tenant_id=tid)

    assert row.tenant_id == esperada.tenant_id
    assert row.max_agents == esperada.max_agents
    assert row.max_agents is not None, "um cliente com plano tem de ter tecto"
