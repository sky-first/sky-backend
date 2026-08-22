"""O que a lista de agentes diz sobre o que eles ANDARAM A FAZER.

Porque existe
-------------
A lista devolvia o que cada agente É — nome, pergunta, cadência — e nada sobre
o que ele TEM FEITO. No ecrã lia-se como uma tabela de tarefas agendadas: nomes
e horários, sem sinal de vida.

E havia uma coisa pior: um agente ACTIVO que falha em silêncio lia-se
exactamente como um que está a correr bem. Um agente parado ao menos diz que
está parado.

O que estes testes guardam
--------------------------
1. O último achado e a última execução chegam na listagem.
2. **Sem `N+1`.** O comentário do `list_by_scope` conta que carregar achados por
   agente esgotou a pousada de ligações quando a web pediu agentes para todos
   os projetos de uma vez. São duas consultas agregadas, e isso tem de
   continuar verdade quando alguém acrescentar o terceiro sinal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.models.agent import Agent, AgentExecution, AgentFinding
from src.repositories.agent import AgentRepository


def _agente(**kw) -> Agent:
    return Agent(
        id=kw.get("id", uuid.uuid4()),
        name=kw.get("name", "Vigia"),
        archetype="custom",
        scope="space",
        scope_id=kw.get("scope_id", "s1"),
        status=kw.get("status", "active"),
        monitor_type="question",
        focus="Que clientes caíram?",
        frequency="daily",
        connection_ids=[],
    )


@pytest.mark.asyncio
async def test_o_ultimo_achado_chega_na_listagem(db_session):
    repo = AgentRepository(db_session)
    a = _agente()
    db_session.add(a)
    await db_session.flush()

    antigo = datetime.now(timezone.utc) - timedelta(days=3)
    recente = datetime.now(timezone.utc)
    db_session.add(
        AgentFinding(
            id=uuid.uuid4(), agent_id=a.id, type="insight", severity="medium",
            title="o velho", description="", created_at=antigo,
        )
    )
    db_session.add(
        AgentFinding(
            id=uuid.uuid4(), agent_id=a.id, type="insight", severity="high",
            title="o mais recente", description="", created_at=recente,
        )
    )
    await db_session.flush()

    (agente,) = await repo.list_by_scope(scope="space", scope_id="s1")

    # O ÚLTIMO, e não o primeiro que a base devolver.
    assert agente.last_finding_title == "o mais recente"
    assert agente.last_finding_at is not None


@pytest.mark.asyncio
async def test_uma_falha_silenciosa_deixa_de_ser_silenciosa(db_session):
    repo = AgentRepository(db_session)
    a = _agente(status="active")
    db_session.add(a)
    await db_session.flush()

    db_session.add(
        AgentExecution(
            id=uuid.uuid4(), agent_id=a.id, status="failed",
            started_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    (agente,) = await repo.list_by_scope(scope="space", scope_id="s1")

    # Está `active` E falhou. Sem este campo, o ecrã mostrava-o igual a um
    # agente saudável — que é pior do que mostrá-lo parado.
    assert agente.status == "active"
    assert agente.last_run_status == "failed"


@pytest.mark.asyncio
async def test_um_agente_que_nunca_correu_nao_inventa_nada(db_session):
    repo = AgentRepository(db_session)
    db_session.add(_agente())
    await db_session.flush()

    (agente,) = await repo.list_by_scope(scope="space", scope_id="s1")

    assert agente.last_finding_title is None
    assert agente.last_finding_at is None
    assert agente.last_run_status is None


@pytest.mark.asyncio
async def test_cada_agente_fica_com_o_SEU_achado(db_session):
    """O `row_number()` particiona por agente. Sem a partição, o achado mais
    recente da tabela inteira aparecia em todos."""
    repo = AgentRepository(db_session)
    a1, a2 = _agente(name="Um"), _agente(name="Dois")
    db_session.add_all([a1, a2])
    await db_session.flush()

    agora = datetime.now(timezone.utc)
    db_session.add(
        AgentFinding(id=uuid.uuid4(), agent_id=a1.id, type="insight", severity="low",
                     title="do primeiro", description="", created_at=agora - timedelta(hours=1))
    )
    db_session.add(
        AgentFinding(id=uuid.uuid4(), agent_id=a2.id, type="insight", severity="low",
                     title="do segundo", description="", created_at=agora)
    )
    await db_session.flush()

    agentes = await repo.list_by_scope(scope="space", scope_id="s1")
    por_nome = {x.name: x for x in agentes}

    assert por_nome["Um"].last_finding_title == "do primeiro"
    assert por_nome["Dois"].last_finding_title == "do segundo"


@pytest.mark.asyncio
async def test_o_custo_nao_cresce_com_o_numero_de_agentes(db_session):
    """Duas consultas agregadas, e não uma por agente.

    Isto é a razão pela qual o `list_by_scope` traz um aviso escrito a dizer
    que os achados NÃO são carregados por agente: já esgotou a pousada de
    ligações uma vez, com a web a pedir agentes para todos os projetos.
    """
    repo = AgentRepository(db_session)
    for i in range(12):
        db_session.add(_agente(name=f"Vigia {i}"))
    await db_session.flush()

    contador = {"n": 0}
    original = db_session.execute

    async def a_contar(*args, **kwargs):
        contador["n"] += 1
        return await original(*args, **kwargs)

    db_session.execute = a_contar  # type: ignore[method-assign]
    try:
        agentes = await repo.list_by_scope(scope="space", scope_id="s1")
    finally:
        db_session.execute = original  # type: ignore[method-assign]

    assert len(agentes) == 12
    # Uma para a lista, uma para os achados, uma para as execuções.
    assert contador["n"] == 3, f"{contador['n']} consultas para 12 agentes"
