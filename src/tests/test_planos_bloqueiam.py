# -*- coding: utf-8 -*-
"""Os planos bloqueiam — e só a Consola os muda.

> «Tudo isso tem que bloquear. Um plano foi estabelecido, tem que ser
>  trocado só na consola.» — Lucas, 10/10/2026

Cada teste é um comportamento de `docs/PLANOS_E_LIMITES_2026-10.md` §6.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.core.tenant_context import TenantContext, reset_current_tenant, set_current_tenant
from src.models.agent import Agent, AgentFrequency, AgentScope
from src.models.connection import DataConnection
from src.models.tenant import Tenant
from src.models.tenant_plan_limits import TenantPlanLimits
from src.services import limites_do_plano as lim
from src.services import planos
from src.tests.conftest import TestSessionLocal

CLIENTE = uuid.uuid4()


@pytest.fixture
def cliente(db_session, monkeypatch):
    """Um cliente resolvido, e a «plataforma» é a base de teste."""
    monkeypatch.setattr(lim, "_sessao_da_plataforma", lambda: TestSessionLocal())
    ctx = TenantContext(slug="mopa", id=CLIENTE, tier="starter", display_name="Mopa")
    token = set_current_tenant(ctx)
    yield db_session
    reset_current_tenant(token)


async def _plano(db, plano="starter", **tectos):
    row = TenantPlanLimits(
        tenant_id=CLIENTE,
        tier=plano,
        **{**planos.tectos(plano), **tectos},
        queries_period_start=datetime.now(timezone.utc),
        last_threshold_alerted={},
    )
    db.add(row)
    await db.commit()
    return row


async def _ligacao(db, apagada=False):
    c = DataConnection(
        id=uuid.uuid4(),
        name=f"c-{uuid.uuid4().hex[:6]}",
        connector_id="postgresql",
        config={},
        created_by=uuid.uuid4(),
    )
    if apagada:
        c.deleted_at = datetime.now(timezone.utc)
    db.add(c)
    await db.commit()


async def _agente(db):
    db.add(
        Agent(
            name="A",
            scope=AgentScope.PERSONAL,
            scope_id=str(uuid.uuid4()),
            scope_name="eu",
            frequency=AgentFrequency.DAILY,
            focus="?",
            created_by=uuid.uuid4(),
            status="active",
        )
    )
    await db.commit()


# ── 1-4. Ligações ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_starter_cria_a_primeira_e_nao_a_segunda_ligacao(cliente):
    await _plano(cliente, "starter")
    await lim.verificar_criacao(cliente, "max_connections")  # a 1.ª passa
    await _ligacao(cliente)
    with pytest.raises(lim.LimiteDoPlanoError) as e:
        await lim.verificar_criacao(cliente, "max_connections")
    assert e.value.status_code == 402
    assert e.value.limit == 1 and e.value.upgrade_hint == "core"
    assert "Starter incluye 1 fuentes de datos" in e.value.messages["es"]


@pytest.mark.asyncio
async def test_uma_ligacao_apagada_nao_conta(cliente):
    await _plano(cliente, "starter")
    await _ligacao(cliente, apagada=True)
    await lim.verificar_criacao(cliente, "max_connections")


@pytest.mark.asyncio
async def test_plano_especial_starter_com_duas_ligacoes(cliente):
    await _plano(cliente, "starter", max_connections=2)
    await _ligacao(cliente)
    await lim.verificar_criacao(cliente, "max_connections")  # a 2.ª passa
    await _ligacao(cliente)
    with pytest.raises(lim.LimiteDoPlanoError):
        await lim.verificar_criacao(cliente, "max_connections")


# ── 5-8. Perguntas ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_pergunta_501_de_um_starter_e_recusada(cliente):
    await _plano(cliente, "starter", current_queries_this_month=499)
    assert await lim.reservar_pergunta() is True  # a 500.ª passa
    with pytest.raises(lim.LimiteDoPlanoError):
        await lim.reservar_pergunta()
    with pytest.raises(lim.LimiteDoPlanoError):
        await lim.verificar_saldo()


@pytest.mark.asyncio
async def test_uma_pergunta_que_falha_nao_gasta(cliente):
    await _plano(cliente, "starter", current_queries_this_month=10)
    await lim.reservar_pergunta()
    await lim.devolver_pergunta()
    async with TestSessionLocal() as s:
        row = (await s.execute(select(TenantPlanLimits))).scalar_one()
    assert row.current_queries_this_month == 10


@pytest.mark.asyncio
async def test_o_aquecimento_da_cache_nao_gasta(cliente):
    await _plano(cliente, "starter", current_queries_this_month=500)
    with lim.sem_contar():
        assert await lim.reservar_pergunta_se_conta() is False


@pytest.mark.asyncio
async def test_o_mes_vira_e_repoe(cliente):
    row = await _plano(cliente, "starter", current_queries_this_month=500)
    row.queries_period_start = datetime.now(timezone.utc) - timedelta(days=40)
    await cliente.commit()
    await lim.verificar_saldo()  # mês novo: há saldo
    assert await lim.reservar_pergunta() is True


# ── 9-10. Agentes ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agente_de_hora_a_hora_nao_cabe_no_starter(cliente):
    await _plano(cliente, "starter")
    with pytest.raises(lim.IntervaloDoPlanoError):
        await lim.verificar_intervalo({"interval_value": 1, "interval_unit": "hour"})
    with pytest.raises(lim.IntervaloDoPlanoError):
        await lim.verificar_intervalo(None, "hourly")
    await lim.verificar_intervalo(None, "daily")


@pytest.mark.asyncio
async def test_o_11_agente_de_um_starter_e_recusado(cliente):
    await _plano(cliente, "starter")
    for _ in range(10):
        await _agente(cliente)
    with pytest.raises(lim.LimiteDoPlanoError):
        await lim.verificar_criacao(cliente, "max_agents")


# ── 11. Armazenamento ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_um_ficheiro_que_passa_os_gb_e_recusado(cliente):
    await _plano(cliente, "starter", max_storage_gb=1)
    await lim.verificar_armazenamento(cliente, 10 * 1024**2)  # 10 MB cabe
    with pytest.raises(lim.LimiteDoPlanoError):
        await lim.verificar_armazenamento(cliente, 2 * 1024**3)


# ── 14-16. De onde vem o plano ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_sem_linha_usa_o_plano_do_registo_e_nao_enterprise(cliente):
    cliente.add(
        Tenant(
            id=CLIENTE,
            slug="mopa",
            display_name="Mopa",
            tier="starter",
            db_host="h",
            db_name="tenant_mopa",
            db_credentials_secret_arn="arn",
            redis_host="r",
            redis_credentials_secret_arn="arn",
            sso_provider="none",
        )
    )
    await cliente.commit()
    plano = await lim.plano_do_cliente()
    assert plano["plano"] == "starter" and plano["max_connections"] == 1


@pytest.mark.asyncio
async def test_plano_desconhecido_recusa_em_vez_de_ilimitado(cliente):
    from src.core.exceptions import ServiceUnavailableError

    with pytest.raises(ServiceUnavailableError):
        await lim.plano_do_cliente()  # nem linha nem registo


@pytest.mark.asyncio
async def test_mudar_plano_na_consola_com_tectos_a_medida(cliente):
    await _plano(cliente, "starter")
    async with TestSessionLocal() as s:
        row = await lim.mudar_plano(s, CLIENTE, "starter", {"max_connections": 2})
        await s.commit()
        assert row.max_connections == 2 and row.personalizado is True
        row = await lim.mudar_plano(s, CLIENTE, "foundation")  # nome antigo
        await s.commit()
        assert row.tier == "core" and row.max_connections == 2 and row.personalizado is False


def test_excessos_ao_baixar_de_plano():
    fora = lim.excessos(
        planos.tectos("starter"), {"ligacoes": 3, "agentes": 5, "armazenamento_bytes": 0}
    )
    assert fora == [{"recurso": "max_connections", "usado": 3, "limite": 1}]


# ── 12. Só a Consola muda o plano ──────────────────────────────────────


@pytest.mark.asyncio
async def test_o_super_admin_do_cliente_nao_muda_o_plano(db_session):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from src.api.v1.tenant_plan import update_tenant_plan

    super_admin = SimpleNamespace(id=uuid.uuid4(), role="super_admin", email="a@mopa.es")
    with pytest.raises(HTTPException) as e:
        await update_tenant_plan(SimpleNamespace(plan_tier="enterprise"), super_admin, db_session)
    assert e.value.status_code == 403


# ── A tabela é a da proposta ───────────────────────────────────────────


def test_a_tabela_e_a_da_proposta_comercial():
    t = {
        s: (
            p.preco_mensal_eur,
            p.tectos["max_connections"],
            p.tectos["max_agents"],
            p.tectos["max_queries_per_month"],
        )
        for s, p in planos.PLANOS.items()
    }
    assert t["starter"] == (490, 1, 10, 500)
    assert t["core"] == (900, 2, 30, 2000)
    assert t["plus"] == (1800, 5, 100, 8000)


def test_as_outras_tabelas_leem_da_mesma():
    from src.models.tenant_plan_limits import TIER_LIMITS
    from src.services import economia_dos_planos, pricing_tiers, tectos_do_plano

    assert TIER_LIMITS["core"]["max_connections"] == 2
    assert pricing_tiers.get_tier("plus").capacity_limits["sources"] == 5
    assert economia_dos_planos.PLANOS["starter"].perguntas_por_mes == 500
    assert tectos_do_plano.tectos_de("scale")[1]["max_agents"] == 100


@pytest.mark.asyncio
async def test_o_402_leva_a_frase_nas_tres_linguas():
    """A app e a web mostram a frase do plano na língua de quem lê."""
    import json

    from fastapi import FastAPI
    from httpx import AsyncClient

    from src.core.errors.handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x")
    async def _x():
        raise lim.LimiteDoPlanoError(recurso="max_connections", limite=1, atual=1, plano="starter")

    async with AsyncClient(app=app, base_url="http://t") as c:
        r = await c.get("/x")
    assert r.status_code == 402
    d = r.json()["error"]["details"]
    assert d["resource"] == "max_connections" and d["limit"] == 1 and d["next_plan"] == "core"
    assert set(d["messages"]) == {"pt", "es", "en"}
