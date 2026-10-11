# -*- coding: utf-8 -*-
"""Agentes com fontes ESCOLHIDAS: o recorte por equipa e o acesso do dono.

Dois buracos fechados aqui, ambos no worker (`agent_worker.py`):

1. Um agente com `connection_ids` escolhidos perguntava SEM `crew_ids`. O
   caminho das fontes do âmbito já os mandava (#741); este não — e o
   `sky-ai` resolvia a equipa sozinho pelo modelo antigo (`crews.space_id`),
   fora do recorte que o chat aplica.
2. As fontes escolhidas não eram reverificadas a cada corrida: quem saía do
   projeto ou da equipa continuava a ter o agente a perguntar com a
   identidade dele.

E o objectivo («¿Qué debe buscar la IA?»): o que se escreve vai à IA; vazio,
vai o objectivo por omissão na língua do dono.

Os testes modelam a sementeira das demonstrações (`scripts/demo_sectorial`):
ligação do PROJETO (`space_connections`), equipa «General» com
`crew_connections`, e o dono do agente é MEMBRO da equipa, não criador da
ligação.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from src.models.agent import Agent
from src.tests.test_agentes_cadencia_e_corridas import (  # noqa: F401 — fixture
    _MotorFalso,
    _correr,
    _dono,
    corrida,
)


async def _demo(db, dono_da_semente):
    """Projeto «Restauración» como a sementeira o deixa."""
    from src.models.connection import DataConnection
    from src.models.crew import Crew, CrewConnection, CrewMember
    from src.models.space import Space, SpaceConnection, SpaceMember
    from src.models.space_crew import SpaceCrew

    projeto = Space(id=uuid.uuid4(), name="Restauración", created_by=dono_da_semente.id)
    db.add(projeto)
    await db.flush()
    db.add(SpaceMember(space_id=projeto.id, user_id=dono_da_semente.id, role="owner"))
    equipa = Crew(
        id=uuid.uuid4(), name="General", space_id=projeto.id, created_by=dono_da_semente.id
    )
    db.add(equipa)
    await db.flush()
    db.add(
        SpaceCrew(
            space_id=projeto.id, crew_id=equipa.id, role="editor", added_by=dono_da_semente.id
        )
    )
    ligacoes = []
    for nome in ("Servicio", "Cocina", "Tiendas"):
        c = DataConnection(
            id=uuid.uuid4(),
            name=nome,
            connector_id="postgresql",
            config={},
            status="active",
            created_by=dono_da_semente.id,
        )
        db.add(c)
        await db.flush()
        db.add(SpaceConnection(space_id=projeto.id, connection_id=c.id))
        db.add(CrewConnection(crew_id=equipa.id, connection_id=c.id))
        ligacoes.append(c)
    await db.commit()
    return projeto, equipa, ligacoes


async def _membro(db, equipa, pessoa):
    from src.models.crew import CrewMember

    db.add(CrewMember(crew_id=equipa.id, user_id=pessoa.id, role="member"))
    await db.commit()


async def _agente(db, dono, *, scope, scope_id, ligacoes=(), monitor_type="datasource", focus=None):
    a = Agent(
        name="Servicio",
        scope=scope,
        scope_id=str(scope_id),
        status="active",
        monitor_type=monitor_type,
        focus=focus,
        frequency="daily",
        connection_ids=[str(c.id) for c in ligacoes],
        created_by=dono.id,
    )
    db.add(a)
    await db.commit()
    return a


# ── 1. O recorte por equipa também nas fontes escolhidas ────────────────


@pytest.mark.asyncio
async def test_agente_de_equipa_com_fonte_escolhida_manda_a_equipa(db_session, corrida):
    """O caso do Lucas: «Una fuente de datos», uma fonte do projeto Restauración."""
    semente = await _dono(db_session)
    lucas = await _dono(db_session, "es")
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[servicio])
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204"}]

    ex = await _correr(db_session, a)

    assert ex.status == "completed"
    assert len(_MotorFalso.chamadas) == 1
    chamada = _MotorFalso.chamadas[0]
    assert chamada["connection_id"] == str(servicio.id)
    assert chamada["crew_ids"] == [str(equipa.id)]
    assert chamada["is_personal"] is False


@pytest.mark.asyncio
async def test_agente_de_projeto_com_fonte_escolhida_manda_as_equipas_do_dono(db_session, corrida):
    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    projeto, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(db_session, lucas, scope="space", scope_id=projeto.id, ligacoes=[servicio])
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204"}]

    await _correr(db_session, a)

    assert _MotorFalso.chamadas[0]["crew_ids"] == [str(equipa.id)]


@pytest.mark.asyncio
async def test_agente_pessoal_vai_em_modo_pessoal(db_session, corrida):
    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(db_session, lucas, scope="personal", scope_id=lucas.id, ligacoes=[servicio])
    _MotorFalso.respostas = [{"answer": "ok"}]

    ex = await _correr(db_session, a)

    assert ex.status == "completed"
    assert _MotorFalso.chamadas[0]["is_personal"] is True
    assert _MotorFalso.chamadas[0]["crew_ids"] is None


# ── 2. O dono tem de alcançar as fontes HOJE ────────────────────────────


@pytest.mark.asyncio
async def test_dono_que_saiu_da_equipa_nao_pergunta_e_diz_porque(db_session, corrida):
    from src.models.crew import CrewMember

    semente = await _dono(db_session)
    lucas = await _dono(db_session, "es")
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[servicio])

    # Tiram-no da equipa depois de criar o agente.
    await db_session.execute(
        delete(CrewMember).where(CrewMember.crew_id == equipa.id, CrewMember.user_id == lucas.id)
    )
    await db_session.commit()

    ex = await _correr(db_session, a)

    assert _MotorFalso.chamadas == [], "não se pergunta com a identidade de quem saiu"
    assert ex.status == "refused_no_access"
    assert str(servicio.id) in (ex.error_message or "")
    assert corrida[-1]["chave"] == "agent_no_access"
    assert "acceso" in corrida[-1]["answer"]  # em castelhano
    # Não é avaria: não soma falhas nem pausa, e volta a tentar.
    assert a.consecutive_failures == 0 and a.status == "active"
    assert a.next_execution_at is not None


@pytest.mark.asyncio
async def test_dono_que_saiu_do_projeto_nao_pergunta(db_session, corrida):
    semente = await _dono(db_session)
    estranho = await _dono(db_session)
    projeto, _, (servicio, _, _) = await _demo(db_session, semente)
    # Sem papel nenhum no projeto (nunca entrou, ou foi removido).
    a = await _agente(db_session, estranho, scope="space", scope_id=projeto.id, ligacoes=[servicio])

    ex = await _correr(db_session, a)

    assert _MotorFalso.chamadas == []
    assert ex.status == "refused_no_access"


@pytest.mark.asyncio
async def test_agente_pessoal_com_fonte_de_projeto_alheio_nao_pergunta(db_session, corrida):
    semente = await _dono(db_session)
    estranho = await _dono(db_session)
    _, _, (servicio, _, _) = await _demo(db_session, semente)
    a = await _agente(
        db_session, estranho, scope="personal", scope_id=estranho.id, ligacoes=[servicio]
    )

    ex = await _correr(db_session, a)

    assert _MotorFalso.chamadas == []
    assert ex.status == "refused_no_access"


@pytest.mark.asyncio
async def test_so_as_fontes_ao_alcance_sao_perguntadas(db_session, corrida):
    """Duas fontes escolhidas, uma de outro projeto: só a do projeto é perguntada."""
    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    _, _, (de_fora, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(
        db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[servicio, de_fora]
    )
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204"}]

    ex = await _correr(db_session, a)

    assert [c["connection_id"] for c in _MotorFalso.chamadas] == [str(servicio.id)]
    assert ex.status == "completed"


@pytest.mark.asyncio
async def test_a_equipa_que_restringiu_as_ligacoes_manda(db_session, corrida):
    """Ligação do projeto mas não da equipa: a equipa restringiu, não se pergunta."""
    from src.models.crew import CrewConnection

    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    _, equipa, (servicio, cocina, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    await db_session.execute(
        delete(CrewConnection).where(
            CrewConnection.crew_id == equipa.id, CrewConnection.connection_id == cocina.id
        )
    )
    await db_session.commit()
    a = await _agente(db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[cocina])

    ex = await _correr(db_session, a)

    assert _MotorFalso.chamadas == []
    assert ex.status == "refused_no_access"


@pytest.mark.asyncio
async def test_a_ligacao_criada_pelo_proprio_dono_e_dele(db_session, corrida):
    lucas = await _dono(db_session)
    from src.models.connection import DataConnection

    minha = DataConnection(
        id=uuid.uuid4(), name="Mía", connector_id="postgresql", config={}, created_by=lucas.id
    )
    db_session.add(minha)
    await db_session.commit()
    a = await _agente(db_session, lucas, scope="personal", scope_id=lucas.id, ligacoes=[minha])
    _MotorFalso.respostas = [{"answer": "ok"}]

    ex = await _correr(db_session, a)

    assert ex.status == "completed" and len(_MotorFalso.chamadas) == 1


# ── 3. O objectivo («¿Qué debe buscar la IA?») ──────────────────────────


async def _agente_do_projeto(db_session, monkeypatch, focus, lingua="es", monitor_type="context"):
    from src.workers import agent_worker

    semente = await _dono(db_session)
    lucas = await _dono(db_session, lingua)
    _, equipa, ligacoes = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)

    async def _ambito(db, agent):
        return [c.id for c in ligacoes]

    monkeypatch.setattr(agent_worker, "_ligacoes_do_ambito", _ambito)
    return await _agente(
        db_session,
        lucas,
        scope="crew",
        scope_id=equipa.id,
        monitor_type=monitor_type,
        focus=focus,
        ligacoes=ligacoes[:1] if monitor_type == "datasource" else (),
    )


@pytest.mark.asyncio
async def test_objetivo_escrito_vai_a_ia(db_session, corrida, monkeypatch):
    a = await _agente_do_projeto(db_session, monkeypatch, "Oportunidades de negocio")
    _MotorFalso.respostas = [{"answer": "ok"}]

    await _correr(db_session, a)

    assert "Oportunidades de negocio" in _MotorFalso.chamadas[0]["instructions"]
    assert _MotorFalso.chamadas[0]["crew_ids"] == [a.scope_id]


@pytest.mark.parametrize(
    "focus", [None, "", "  ", "Scan all data for anomalies, trends, risks, and opportunities."]
)
@pytest.mark.asyncio
async def test_sem_objetivo_vai_o_de_omissao_na_lingua_do_dono(
    db_session, corrida, monkeypatch, focus
):
    a = await _agente_do_projeto(db_session, monkeypatch, focus)
    _MotorFalso.respostas = [{"answer": "ok"}]

    await _correr(db_session, a)

    instrucoes = _MotorFalso.chamadas[0]["instructions"]
    assert "oportunidades de negocio" in instrucoes
    assert "amenazas y alertas" in instrucoes
    assert "Scan all data" not in instrucoes


@pytest.mark.asyncio
async def test_objetivo_de_omissao_em_portugues(db_session, corrida, monkeypatch):
    a = await _agente_do_projeto(db_session, monkeypatch, None, lingua="pt")
    _MotorFalso.respostas = [{"answer": "ok"}]

    await _correr(db_session, a)

    assert "ameaças e alertas" in _MotorFalso.chamadas[0]["instructions"]


@pytest.mark.asyncio
async def test_objetivo_tambem_no_modo_uma_fonte(db_session, corrida, monkeypatch):
    a = await _agente_do_projeto(
        db_session, monkeypatch, "Fallos en mi operación", monitor_type="datasource"
    )
    _MotorFalso.respostas = [{"answer": "ok"}]

    await _correr(db_session, a)

    assert "Fallos en mi operación" in _MotorFalso.chamadas[0]["instructions"]


@pytest.mark.asyncio
async def test_objetivo_e_gravado_pela_api_e_lido_de_volta(db_session):
    """A app grava o objectivo no `focus` — criar e actualizar guardam-no."""
    from src.schemas.agent import AgentCreate, AgentUpdate
    from src.services.agent_service import AgentService

    lucas = await _dono(db_session)

    async def _sem_ingest(*a, **k):
        return None

    svc = AgentService(db_session)
    svc.ai_client.ingest_knowledge_graph = _sem_ingest
    criado = await svc.create_agent(
        AgentCreate(
            name="Todo",
            scope="personal",
            monitor_type="context",
            focus="Amenazas y alertas",
            frequency="manual",
        ),
        user_id=lucas.id,
    )
    assert criado.focus == "Amenazas y alertas"
    await svc.update_agent(criado.id, AgentUpdate(focus="Formas de mejorar mi negocio"), lucas)
    agente = await db_session.get(Agent, criado.id)
    await db_session.refresh(agente)
    assert agente.focus == "Formas de mejorar mi negocio"
