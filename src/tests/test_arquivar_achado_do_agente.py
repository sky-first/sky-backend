"""Arquivar um achado: só um achado DESTE agente, e só quem pode no âmbito dele.

`POST /agents/{agent_id}/findings/{finding_id}/dismiss` verificava apenas a
permissão genérica do cliente e ignorava o `agent_id` do caminho. Quem tivesse
`agents.findings.dismiss` arquivava o achado de qualquer agente, de qualquer
equipa — bastava pôr o id atrás do de um agente seu. Ler esses achados exige
ser da equipa; arquivá-los não pode exigir menos.

E o `agent_id` do achado no feed das Descobertas (a app leva o toque ao agente
por ele, em vez de adivinhar pelo nome).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from src.api.v1 import agents as rota
from src.models.agent import Agent, AgentFinding
from src.services.agent_service import AgentService
from src.tests.test_quem_ve_o_que_no_projeto import _montar_a_empresa


async def _agente_da_equipa(db, equipa, dono, nome="Salários"):
    a = Agent(
        name=nome,
        scope="crew",
        scope_id=str(equipa.id),
        status="active",
        monitor_type="question",
        focus="Quanto pagámos?",
        frequency="manual",
        connection_ids=[],
        created_by=dono.id,
    )
    db.add(a)
    await db.flush()
    achado = AgentFinding(
        agent_id=a.id,
        type="insight",
        severity="medium",
        title=f"{nome}: subiu 4%",
        description="…",
        confidence=0.75,
    )
    db.add(achado)
    await db.commit()
    return a, achado


async def _arquivar(db, quem, agent_id, finding_id):
    return await rota.dismiss_finding(
        agent_id=agent_id,
        finding_id=finding_id,
        current_user=quem,
        db=db,
        service=AgentService(db),
    )


@pytest.mark.asyncio
async def test_quem_e_da_equipa_arquiva_o_achado_do_agente_dela(db_session):
    e = await _montar_a_empresa(db_session)
    agente, achado = await _agente_da_equipa(db_session, e["payroll"], e["bruno"])

    resposta = await _arquivar(db_session, e["bruno"], agente.id, achado.id)
    assert str(resposta.id) == str(achado.id)
    await db_session.refresh(achado)
    assert achado.dismissed_at is not None or getattr(achado, "dismissed", False)


@pytest.mark.asyncio
async def test_um_achado_pelo_caminho_de_outro_agente_da_404(db_session):
    """O Diogo tem um agente seu (Campanhas). Pôr o achado da Payroll atrás
    desse id não o deixa arquivar — e não confirma que o achado existe."""
    e = await _montar_a_empresa(db_session)
    _, achado_alheio = await _agente_da_equipa(db_session, e["payroll"], e["bruno"])
    meu, _ = await _agente_da_equipa(db_session, e["campanhas"], e["diogo"], nome="Campanhas")

    with pytest.raises(HTTPException) as recusa:
        await _arquivar(db_session, e["diogo"], meu.id, achado_alheio.id)
    assert recusa.value.status_code == 404
    await db_session.refresh(achado_alheio)
    assert achado_alheio.dismissed_at is None


@pytest.mark.asyncio
async def test_membro_de_outra_equipa_nao_arquiva(db_session):
    """A Ana é do mesmo projeto (Financeiro), mas da equipa Contas."""
    e = await _montar_a_empresa(db_session)
    agente, achado = await _agente_da_equipa(db_session, e["payroll"], e["bruno"])

    for quem in (e["ana"], e["diogo"], e["carla"]):
        with pytest.raises(HTTPException) as recusa:
            await _arquivar(db_session, quem, agente.id, achado.id)
        assert recusa.value.status_code == 403, quem.name
    await db_session.refresh(achado)
    assert achado.dismissed_at is None


@pytest.mark.asyncio
async def test_agente_inexistente_da_404(db_session):
    e = await _montar_a_empresa(db_session)
    with pytest.raises(HTTPException) as recusa:
        await _arquivar(db_session, e["bruno"], uuid.uuid4(), uuid.uuid4())
    assert recusa.value.status_code == 404


# ── O agente no feed ─────────────────────────────────────────────────


def test_o_item_do_feed_leva_o_agente():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from src.services.insight_feed_service import InsightFeedService

    aid = uuid.uuid4()
    f = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=aid,
        type="insight",
        severity="medium",
        agent_name=None,
        title="t",
        description="d",
        source="agent",
        series=[],
        created_at=datetime.now(timezone.utc),
    )
    agente = SimpleNamespace(name="Vendas", conversation_id=None, status="paused")
    item = InsightFeedService._to_item(InsightFeedService.__new__(InsightFeedService), f, agente, None)
    assert item.agent_id == str(aid)

    f.agent_id = None  # varredura: sem agente
    item = InsightFeedService._to_item(InsightFeedService.__new__(InsightFeedService), f, None, None)
    assert item.agent_id is None
