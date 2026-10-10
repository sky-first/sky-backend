# -*- coding: utf-8 -*-
"""Check-up dos agentes: cadência, corridas, plano, Descobertas.

> «Correr agora não existe, as frequências são grosseiras, e o agente que
>  criei correu e não aparece nas Descobertas.» — Lucas, 10/10/2026

Estes testes CORREM o worker (com um motor de IA falso) em vez de lerem o
código-fonte: os testes que fixam o texto do código deixaram passar, mais de
uma vez, um comportamento errado.

Defeitos que cada bloco apanha (todos vistos no código de 10/10):

* um agente «de 15 em 15 min» passava a correr 1×/dia depois da 1.ª corrida
  (o worker tinha uma tabela de frequências sem `minutely`);
* `minutely` sem unidade passava o portão do plano de qualquer cliente;
* um agente sem fontes escolhidas (o que a app cria) NÃO perguntava nada e o
  fio dizia «olhei e não há nada a assinalar»;
* uma excepção qualquer punha o agente em `error` — parado para sempre;
* sem perguntas no mês a meio da corrida contava como falha e auto-pausava;
* retomar um agente auto-pausado deixava o contador de falhas em 3;
* a frase «nada a assinalar» saía sempre em português.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from src.models.agent import Agent, AgentExecution, AgentFinding
from src.services import cadencia_do_agente as cad
from src.services import limites_do_plano as lim

AGORA = datetime(2026, 10, 10, 15, 47, tzinfo=timezone.utc)  # sábado


# ── 1. A cadência, para cada opção da app ────────────────────────────────


@pytest.mark.parametrize(
    "cfg,frequencia,minutos",
    [
        ({"interval_value": 1, "interval_unit": "minute"}, "manual", 1),
        ({"interval_value": 5, "interval_unit": "minute"}, "manual", 5),
        ({"interval_value": 10, "interval_unit": "minute"}, "manual", 10),
        ({"interval_value": 15, "interval_unit": "minute"}, "manual", 15),
        ({"interval_value": 30, "interval_unit": "minute"}, "manual", 30),
        ({"interval_value": 1, "interval_unit": "hour"}, "hourly", 60),
        ({"interval_value": 2, "interval_unit": "hour"}, "hourly", 120),
        ({"interval_value": 6, "interval_unit": "hour"}, "hourly", 360),
        ({"interval_value": 12, "interval_unit": "hour"}, "hourly", 720),
        ({"interval_value": 1, "interval_unit": "day"}, "daily", 1440),
        ({"interval_value": 2, "interval_unit": "day"}, "daily", 2880),
        ({"interval_value": 3, "interval_unit": "day"}, "daily", 4320),
        ({"interval_value": 1, "interval_unit": "week"}, "weekly", 10080),
        (None, "minutely", 1),
        (None, "hourly", 60),
        (None, "daily", 1440),
        (None, "weekly", 10080),
        # Como o `_compute_next_execution` antigo o lia: valor × frequência.
        ({"interval_value": 3}, "hourly", 180),
    ],
)
def test_cada_opcao_tem_o_intervalo_certo_e_a_proxima_corrida_bate(cfg, frequencia, minutos):
    assert cad.intervalo_em_minutos(cfg, frequencia) == minutos
    assert cad.proxima_corrida(AGORA, frequencia, cfg) == AGORA + timedelta(minutes=minutos)


def test_manual_e_uma_so_vez_nao_correm_sozinhos():
    assert cad.proxima_corrida(AGORA, "manual", None) is None
    assert cad.proxima_corrida(AGORA, "once", {}) is None
    assert cad.intervalo_em_minutos(None, "manual") is None


def test_dias_da_semana_seg_qua_sex_as_9_em_madrid():
    cfg = {"weekdays": [0, 2, 4], "hour": 9, "minute": 0, "timezone": "Europe/Madrid"}
    p = cad.proxima_corrida(AGORA, "manual", cfg)  # sábado → segunda
    local = p.astimezone(ZoneInfo("Europe/Madrid"))
    assert (local.weekday(), local.hour, local.minute) == (0, 9, 0)
    assert local.date() == datetime(2026, 10, 12).date()
    # Depois de segunda às 9h, é quarta.
    p2 = cad.proxima_corrida(p, "manual", cfg)
    assert p2.astimezone(ZoneInfo("Europe/Madrid")).weekday() == 2
    # O plano vê o intervalo mais curto: 2 dias (seg→qua).
    assert cad.intervalo_em_minutos(cfg) == 2 * 1440


def test_dias_da_semana_aceitam_nomes_e_hora_por_omissao():
    cfg = cad.normalizar({"weekdays": ["mon", "thu"]})
    assert cfg["weekdays"] == [0, 3]
    p = cad.proxima_corrida(AGORA, "manual", cfg)
    assert (p.weekday(), p.hour) == (0, cad.HORA_POR_OMISSAO)
    assert cad.intervalo_em_minutos({"weekdays": [0, 1]}) == 1440
    assert cad.intervalo_em_minutos({"weekdays": [3]}) == 7 * 1440


def test_dia_sim_dia_nao_as_8_30_alinha_a_hora():
    cfg = {"interval_value": 2, "interval_unit": "day", "hour": 8, "minute": 30}
    p = cad.proxima_corrida(AGORA, "daily", cfg)
    assert (p.hour, p.minute) == (8, 30)
    assert AGORA < p <= AGORA + timedelta(days=2)


def test_a_hora_que_a_web_grava_como_texto_e_lida():
    """A web grava `time: "08:00"` — e o agendador ignorava-o."""
    assert cad.hora_escolhida({"time": "08:00 UTC"}) == (8, 0)
    p = cad.proxima_corrida(AGORA, "daily", {"interval_unit": "day", "time": "08:00"})
    assert (p.hour, p.minute) == (8, 0)


def test_nunca_agenda_no_passado_nem_no_proprio_instante():
    em_ponto = AGORA.replace(hour=9, minute=0)
    assert cad.proxima_corrida(em_ponto, "daily", {"hour": 9}) > em_ponto
    cfg = {"weekdays": [5], "hour": 15, "minute": 47}  # sábado 15:47 UTC = AGORA
    assert cad.proxima_corrida(AGORA, "manual", cfg) == AGORA + timedelta(days=7)


@pytest.mark.parametrize(
    "mau",
    [
        {"weekdays": [9]},
        {"weekdays": "seg"},
        {"interval_value": 0, "interval_unit": "minute"},
        {"interval_value": "x"},
        {"interval_unit": "fortnight"},
        {"timezone": "Marte/Olimpo"},
        {"hour": "oito"},
    ],
)
def test_um_schedule_ilegivel_e_recusado_a_escrita(mau):
    with pytest.raises(cad.CadenciaInvalida):
        cad.normalizar(mau)


def test_a_leitura_e_tolerante():
    """Um blob estragado na base não pode parar o agendador."""
    assert cad.proxima_corrida(AGORA, "daily", {"weekdays": "lixo"}) == AGORA + timedelta(days=1)
    assert cad.proxima_corrida(AGORA, "daily", "lixo") == AGORA + timedelta(days=1)


# ── 2. O portão do plano usa a MESMA regra ──────────────────────────────


@pytest.fixture
def plano(db_session, monkeypatch):
    """Um cliente com plano, na base de teste."""
    from src.core.tenant_context import TenantContext, reset_current_tenant, set_current_tenant
    from src.models.tenant_plan_limits import TenantPlanLimits
    from src.services import planos
    from src.tests.conftest import TestSessionLocal

    cliente = uuid.uuid4()
    monkeypatch.setattr(lim, "_sessao_da_plataforma", lambda: TestSessionLocal())
    token = set_current_tenant(
        TenantContext(slug="mopa", id=cliente, tier="core", display_name="Mopa")
    )

    async def _com(slug: str, **tectos):
        db_session.add(
            TenantPlanLimits(
                tenant_id=cliente,
                tier=slug,
                **{**planos.tectos(slug), **tectos},
                queries_period_start=datetime.now(timezone.utc),
                last_threshold_alerted={},
            )
        )
        await db_session.commit()

    yield _com
    reset_current_tenant(token)


@pytest.mark.asyncio
async def test_minutely_sem_unidade_ja_nao_passa_o_portao(plano):
    await plano("core")  # mínimo 60 min
    with pytest.raises(lim.IntervaloDoPlanoError):
        await lim.verificar_intervalo(None, "minutely")
    with pytest.raises(lim.IntervaloDoPlanoError):
        await lim.verificar_intervalo({"interval_value": 30, "interval_unit": "minute"}, "manual")
    await lim.verificar_intervalo({"interval_value": 1, "interval_unit": "hour"}, "hourly")
    # Dias da semana: o intervalo mais curto é 1 dia — cabe no Core.
    await lim.verificar_intervalo({"weekdays": [0, 1, 2]}, "manual")


@pytest.mark.asyncio
async def test_enterprise_deixa_5_minutos_e_nao_menos(plano):
    await plano("enterprise")
    await lim.verificar_intervalo({"interval_value": 5, "interval_unit": "minute"}, "manual")
    with pytest.raises(lim.IntervaloDoPlanoError):
        await lim.verificar_intervalo({"interval_value": 1, "interval_unit": "minute"}, "manual")


# ── 3. As corridas, com um motor de IA falso ────────────────────────────


class _MotorFalso:
    """Faz de `AIServiceHTTPClient`. Guarda cada pergunta que recebeu."""

    respostas: list = []
    chamadas: list = []
    classificar_rebenta = False

    def __init__(self, *a, **k):
        pass

    async def query_connection(self, **kw):
        _MotorFalso.chamadas.append(kw)
        r = _MotorFalso.respostas.pop(0) if _MotorFalso.respostas else {"answer": ""}
        if isinstance(r, Exception):
            raise r
        return r

    async def classificar_achado(self, **kw):
        if _MotorFalso.classificar_rebenta:
            raise RuntimeError("base a piscar")
        return {"type": "insight", "severity": "medium"}


@pytest.fixture
def corrida(db_session, monkeypatch):
    """Liga o worker à base de teste e ao motor falso; guarda o que se publica."""
    from src.ai import http_client
    from src.config import tenant_connection_manager as tcm
    from src.services import agent_conversation_service as conv

    @asynccontextmanager
    async def _sessao(_ctx=None):
        yield db_session

    monkeypatch.setattr(tcm.tenant_connection_manager, "session_for", _sessao)
    monkeypatch.setattr(http_client, "AIServiceHTTPClient", _MotorFalso)
    _MotorFalso.respostas = []
    _MotorFalso.chamadas = []
    _MotorFalso.classificar_rebenta = False

    publicadas: list = []

    async def _publicar(db, *, agent, answer, finding_id=None, chave_de_texto=None):
        publicadas.append({"answer": answer, "finding_id": finding_id, "chave": chave_de_texto})
        return None

    monkeypatch.setattr(conv, "post_agent_answer", _publicar)
    return publicadas


async def _dono(db, lingua="pt"):
    from src.core.security import get_password_hash
    from src.repositories.user import UserRepository

    u = await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Dono",
        role="member",
    )
    u.preferences = {"language": lingua}
    await db.commit()
    return u


async def _ligacao(db, dono):
    from src.models.connection import DataConnection

    c = DataConnection(
        id=uuid.uuid4(),
        name="Ventas",
        connector_id="postgresql",
        config={},
        created_by=dono.id,
    )
    db.add(c)
    await db.commit()
    return c


async def _agente(db, dono, *, ligacoes=(), schedule=None, frequency="daily", **extra):
    a = Agent(
        name="¿Cuánto he facturado?",
        scope="personal",
        scope_id=str(dono.id),
        status="active",
        monitor_type="question",
        focus="¿Cuánto he facturado?",
        frequency=frequency,
        schedule_jsonb=schedule,
        connection_ids=[str(x) for x in ligacoes],
        created_by=dono.id,
        **extra,
    )
    db.add(a)
    await db.commit()
    return a


async def _correr(db, agente, a_pedido=False):
    from src.workers.agent_worker import _execute_agent_async

    await _execute_agent_async(str(agente.id), a_pedido=a_pedido)
    await db.refresh(agente)
    execs = (
        (
            await db.execute(
                select(AgentExecution)
                .where(AgentExecution.agent_id == agente.id)
                .order_by(AgentExecution.started_at)
            )
        )
        .scalars()
        .all()
    )
    return execs[-1] if execs else None


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_uma_corrida_com_resposta_vira_descoberta_e_mensagem(db_session, corrida):
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    _MotorFalso.respostas = [{"answer": "Facturación: 6.153.185,72 €", "title": "Facturación"}]

    ex = await _correr(db_session, a)

    assert ex.status == "completed" and ex.findings_count == 1
    achados = (await db_session.execute(select(AgentFinding))).scalars().all()
    assert len(achados) == 1 and "6.153.185,72" in achados[0].description
    assert corrida[-1]["finding_id"] == achados[0].id
    assert a.consecutive_failures == 0 and a.status == "active"


@pytest.mark.asyncio
async def test_de_15_em_15_minutos_continua_de_15_em_15(db_session, corrida):
    """O defeito: depois da 1.ª corrida, o worker reagendava para daqui a 24 h."""
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(
        db_session,
        dono,
        ligacoes=[c.id],
        frequency="minutely",
        schedule={"interval_value": 15, "interval_unit": "minute"},
    )
    _MotorFalso.respostas = [{"answer": "Facturación: 10 €"}]
    antes = datetime.now(timezone.utc)
    await _correr(db_session, a)
    proxima = _aware(a.next_execution_at)
    assert antes + timedelta(minutes=14) < proxima <= antes + timedelta(minutes=16)


@pytest.mark.asyncio
async def test_dias_da_semana_caem_no_dia_certo(db_session, corrida):
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    cfg = {"weekdays": [0, 2, 4], "hour": 9, "minute": 0, "timezone": "Europe/Madrid"}
    a = await _agente(db_session, dono, ligacoes=[c.id], frequency="manual", schedule=cfg)
    _MotorFalso.respostas = [{"answer": "Facturación: 10 €"}]
    await _correr(db_session, a)
    local = _aware(a.next_execution_at).astimezone(ZoneInfo("Europe/Madrid"))
    assert local.weekday() in (0, 2, 4) and (local.hour, local.minute) == (9, 0)


@pytest.mark.asyncio
async def test_sem_fontes_escolhidas_pergunta_as_do_ambito(db_session, corrida, monkeypatch):
    """O agente do Lucas: criado na app, sem `connection_ids` — nunca perguntava nada."""
    from src.workers import agent_worker

    dono = await _dono(db_session, "es")
    c1, c2 = await _ligacao(db_session, dono), await _ligacao(db_session, dono)

    async def _ambito(db, agent):
        return [c1.id, c2.id]

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _ambito)
    a = await _agente(db_session, dono)
    _MotorFalso.respostas = [{"answer": "Has facturado 6.153.185,72 €"}]

    ex = await _correr(db_session, a)

    # UMA pergunta só, com as duas fontes — não uma por fonte.
    assert len(_MotorFalso.chamadas) == 1
    chamada = _MotorFalso.chamadas[0]
    assert chamada["connection_id"] == str(c1.id)
    assert set(chamada["connection_ids"]) == {str(c1.id), str(c2.id)}
    assert chamada["locale"] == "es"
    assert ex.findings_count == 1


@pytest.mark.asyncio
async def test_sem_fonte_nenhuma_diz_o_que_e_e_nao_conta_como_falha(
    db_session, corrida, monkeypatch
):
    from src.workers import agent_worker

    async def _nada(db, agent):
        return []

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _nada)
    dono = await _dono(db_session, "es")
    a = await _agente(db_session, dono)

    ex = await _correr(db_session, a)

    assert _MotorFalso.chamadas == []
    assert ex.status == "failed"
    assert corrida[-1]["chave"] == "agent_no_data_source"
    assert "fuente" in corrida[-1]["answer"]  # em castelhano
    assert a.consecutive_failures == 0 and a.status == "active"
    assert a.next_execution_at is not None


@pytest.mark.asyncio
async def test_nada_a_assinalar_sai_na_lingua_do_dono(db_session, corrida):
    dono = await _dono(db_session, "es")
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    _MotorFalso.respostas = [{"answer": ""}]

    ex = await _correr(db_session, a)

    assert ex.status == "completed"
    assert corrida[-1]["chave"] == "agent_nothing_to_report"
    assert corrida[-1]["answer"].startswith("Acabo de mirar")
    # Uma resposta vazia não é avaria: não soma falhas.
    assert a.consecutive_failures == 0 and a.status == "active"


@pytest.mark.asyncio
async def test_sem_perguntas_no_mes_salta_sem_contar_falha(db_session, corrida, monkeypatch):
    async def _sem_saldo():
        raise lim.LimiteDoPlanoError(
            recurso="max_queries_per_month", limite=500, atual=500, plano="starter"
        )

    monkeypatch.setattr(lim, "verificar_saldo", _sem_saldo)
    dono = await _dono(db_session, "es")
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])

    ex = await _correr(db_session, a, a_pedido=True)

    assert ex.status == "skipped_plan_quota"
    assert _MotorFalso.chamadas == []
    assert corrida[-1]["chave"] == "agent_skipped_plan_quota"
    assert "preguntas" in corrida[-1]["answer"]
    assert a.consecutive_failures == 0 and a.status == "active"


@pytest.mark.asyncio
async def test_perguntas_acabam_a_meio_nao_e_falha(db_session, corrida):
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    _MotorFalso.respostas = [
        lim.LimiteDoPlanoError(
            recurso="max_queries_per_month", limite=500, atual=500, plano="starter"
        )
    ]

    ex = await _correr(db_session, a)

    assert ex.status == "skipped_plan_quota"
    assert a.consecutive_failures == 0 and a.status == "active"


@pytest.mark.asyncio
async def test_uma_excepcao_nao_mata_o_agente_e_tres_seguidas_pausam(db_session, corrida):
    """Antes: `status = "error"` à primeira, e o agendador nunca mais o via."""
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    _MotorFalso.classificar_rebenta = True

    for n in (1, 2):
        _MotorFalso.respostas = [{"answer": "Facturación: 1 €"}]
        ex = await _correr(db_session, a)
        assert ex.status == "failed"
        assert a.status == "active", "uma excepção não pode parar o agente"
        assert a.consecutive_failures == n
        assert a.next_execution_at is not None

    _MotorFalso.respostas = [{"answer": "Facturación: 1 €"}]
    await _correr(db_session, a)
    assert a.status == "paused" and a.next_execution_at is None


@pytest.mark.asyncio
async def test_todas_as_fontes_falham_conta_e_reagenda(db_session, corrida):
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    _MotorFalso.respostas = [RuntimeError("HTTPStatusError 500")]

    ex = await _correr(db_session, a)

    assert ex.status == "failed"
    assert corrida[-1]["chave"] == "agent_could_not_run"
    assert a.consecutive_failures == 1 and a.status == "active"
    assert _aware(a.next_execution_at) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_pedido_directo_a_um_agente_em_pausa_corre_e_continua_em_pausa(db_session, corrida):
    dono = await _dono(db_session)
    c = await _ligacao(db_session, dono)
    a = await _agente(db_session, dono, ligacoes=[c.id])
    a.status = "paused"
    a.next_execution_at = None
    await db_session.commit()
    _MotorFalso.respostas = [{"answer": "Facturación: 1 €"}]

    ex = await _correr(db_session, a, a_pedido=True)

    assert ex.status == "completed"
    assert a.status == "paused" and a.next_execution_at is None


@pytest.mark.asyncio
async def test_o_agendador_devolve_os_agentes_presos_em_error(db_session, monkeypatch):
    from src.workers import agent_worker

    @asynccontextmanager
    async def _sessao(_ctx=None):
        yield db_session

    from src.config import tenant_connection_manager as tcm

    monkeypatch.setattr(tcm.tenant_connection_manager, "session_for", _sessao)
    monkeypatch.setattr(agent_worker.execute_agent, "delay", lambda *a, **k: None)
    dono = await _dono(db_session)
    a = Agent(
        name="preso",
        scope="personal",
        scope_id=str(dono.id),
        status="error",
        monitor_type="question",
        frequency="hourly",
        connection_ids=[],
        created_by=dono.id,
    )
    db_session.add(a)
    await db_session.commit()

    await agent_worker._schedule_agents_async()
    await db_session.refresh(a)

    assert a.status == "active"
    assert _aware(a.next_execution_at) > datetime.now(timezone.utc)


# ── 4. As fontes do âmbito ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agente_de_equipa_ve_as_ligacoes_do_projeto_e_respeita_as_da_equipa(
    db_session, monkeypatch
):
    from src.models.crew import Crew, CrewConnection
    from src.models.space import Space
    from src.services.ai_service import AIService
    from src.workers.agent_worker import _ligacoes_do_ambito

    dono = await _dono(db_session)
    c1, c2 = await _ligacao(db_session, dono), await _ligacao(db_session, dono)
    projeto = Space(id=uuid.uuid4(), name="P", created_by=dono.id)
    db_session.add(projeto)
    await db_session.flush()
    equipa = Crew(id=uuid.uuid4(), name="General", space_id=projeto.id, created_by=dono.id)
    db_session.add(equipa)
    await db_session.commit()

    pedidos = []

    async def _do_projeto(self, user_id, space_id):
        pedidos.append((user_id, space_id))
        return [str(c1.id), str(c2.id)]

    monkeypatch.setattr(AIService, "_get_all_connections_for_space", _do_projeto)
    a = Agent(
        name="x",
        scope="crew",
        scope_id=str(equipa.id),
        status="active",
        frequency="daily",
        connection_ids=[],
        created_by=dono.id,
    )

    assert set(await _ligacoes_do_ambito(db_session, a)) == {c1.id, c2.id}
    assert pedidos == [(dono.id, str(projeto.id))]

    # A equipa restringiu: só a dela.
    db_session.add(CrewConnection(crew_id=equipa.id, connection_id=c2.id))
    await db_session.commit()
    assert await _ligacoes_do_ambito(db_session, a) == [c2.id]


# ── 5. Serviço: criar, editar, retomar ───────────────────────────────────


@pytest.mark.asyncio
async def test_criar_guarda_o_schedule_e_agenda_por_ele(db_session):
    from src.schemas.agent import AgentCreate
    from src.services.agent_service import AgentService

    dono = await _dono(db_session)
    svc = AgentService(db_session)

    async def _sem_ingest(*a, **k):
        return None

    svc.ai_client.ingest_knowledge_graph = _sem_ingest
    cfg = {"interval_value": 30, "interval_unit": "minute"}
    a = await svc.create_agent(
        AgentCreate(name="x", scope="personal", focus="?", frequency="manual", schedule_jsonb=cfg),
        user_id=dono.id,
    )
    assert a.schedule_jsonb == cfg
    falta = _aware(a.next_execution_at) - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < falta <= timedelta(minutes=30)


@pytest.mark.asyncio
async def test_criar_com_schedule_ilegivel_da_422(db_session):
    from fastapi import HTTPException

    from src.schemas.agent import AgentCreate
    from src.services.agent_service import AgentService

    dono = await _dono(db_session)
    with pytest.raises(HTTPException) as e:
        await AgentService(db_session).create_agent(
            AgentCreate(name="x", scope="personal", schedule_jsonb={"weekdays": [8]}),
            user_id=dono.id,
        )
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_mudar_a_cadencia_muda_ja_a_proxima_corrida(db_session):
    from src.schemas.agent import AgentUpdate
    from src.services.agent_service import AgentService

    dono = await _dono(db_session)
    a = await _agente(
        db_session, dono, next_execution_at=datetime.now(timezone.utc) + timedelta(days=1)
    )
    await AgentService(db_session).update_agent(
        a.id,
        AgentUpdate(schedule_jsonb={"interval_value": 1, "interval_unit": "hour"}),
        dono,
    )
    await db_session.refresh(a)
    falta = _aware(a.next_execution_at) - datetime.now(timezone.utc)
    assert timedelta(minutes=59) < falta <= timedelta(hours=1)


@pytest.mark.asyncio
async def test_retomar_poe_o_contador_de_falhas_a_zero(db_session):
    from src.services.agent_service import AgentService

    dono = await _dono(db_session)
    a = await _agente(db_session, dono, consecutive_failures=3)
    a.status = "paused"
    await db_session.commit()
    await AgentService(db_session).resume_agent(a.id)
    await db_session.refresh(a)
    assert a.status == "active" and a.consecutive_failures == 0


# ── 6. As Descobertas mostram TODOS os agentes ──────────────────────────


@pytest.mark.asyncio
async def test_descobertas_mostram_cada_agente_com_a_ultima_corrida(db_session):
    from src.services.insight_feed_service import InsightFeedService

    dono = await _dono(db_session)
    calado = await _agente(db_session, dono)
    falhou = await _agente(db_session, dono)
    respondeu = await _agente(db_session, dono)
    nunca = await _agente(db_session, dono)
    agora = datetime.now(timezone.utc)
    db_session.add_all(
        [
            AgentExecution(
                agent_id=calado.id, status="completed", findings_count=0, finished_at=agora
            ),
            AgentExecution(
                agent_id=falhou.id, status="failed", error_message="x", finished_at=agora
            ),
            AgentExecution(
                agent_id=respondeu.id,
                status="completed",
                findings_count=1,
                answer="Facturación: 6.153.185,72 €",
                finished_at=agora,
            ),
        ]
    )
    await db_session.commit()

    feed = await InsightFeedService(db_session).list(dono.id, "all", None, 20)
    por_id = {g.id: g for g in feed.agentes}

    assert set(por_id) == {str(x.id) for x in (calado, falhou, respondeu, nunca)}
    assert por_id[str(calado.id)].chave_de_texto == "agent_nothing_to_report"
    assert por_id[str(falhou.id)].chave_de_texto == "agent_could_not_run"
    assert por_id[str(respondeu.id)].ultima_resposta == "Facturación: 6.153.185,72 €"
    assert por_id[str(respondeu.id)].encontrou is True
    assert por_id[str(nunca.id)].ultima_corrida_estado is None

    # Com busca ou noutra página, não vem.
    assert (
        await InsightFeedService(db_session).list(dono.id, "all", None, 20, q="x")
    ).agentes == []


@pytest.mark.asyncio
async def test_descobertas_nao_mostram_agentes_de_quem_nao_e_membro(db_session):
    from src.services.insight_feed_service import InsightFeedService

    dono = await _dono(db_session)
    outro = await _dono(db_session)
    await _agente(db_session, dono)
    feed = await InsightFeedService(db_session).list(outro.id, "all", None, 20)
    assert feed.agentes == []
