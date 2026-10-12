# -*- coding: utf-8 -*-
"""O achado de um agente avisa quem vê os dados dele (auditoria web, 12/10/2026).

O envio para o projeto só corria com ``agent.scope == "space"``
(``agent_worker.py``), e todos os agentes nascem ``crew``: na prática o achado
só chegava a quem criou o agente. Agora:

* agente de equipa → os membros da equipa;
* com ``DATA_BOUNDARY=project`` → o projeto da equipa;
* agente de projeto → toda a gente do projeto;
* quem silenciou o agente não recebe (preferências);
* quem NÃO vê os dados (fora da equipa, mesmo sendo admin ou dono do projeto)
  não recebe: a máscara de conteúdo também vale para o aviso;
* quem criou recebe uma vez só (pela via com ``deep_link``).
"""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import select

from src.tests.test_agente_fontes_escolhidas_e_equipa import _agente, _demo, _membro
from src.tests.test_agentes_cadencia_e_corridas import (  # noqa: F401 — fixture
    _MotorFalso,
    _correr,
    _dono,
    corrida,
)


async def _avisos(db, agente):
    from src.models.notification import Notification

    linhas = (
        (
            await db.execute(
                select(Notification.user_id).where(
                    Notification.type == "agent_finding",
                    Notification.entity_id == str(agente.id),
                )
            )
        )
        .scalars()
        .all()
    )
    return Counter(linhas)


async def _silenciar(db, pessoa, agente):
    from src.models.notification import NotificationPreference

    db.add(
        NotificationPreference(
            user_id=pessoa.id,
            scope_type="source",
            scope_value=f"agent:{agente.id}",
            channel="all",
            enabled=False,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_achado_de_agente_de_equipa_avisa_a_equipa_e_so_a_equipa(db_session, corrida):
    semente = await _dono(db_session)  # dono do projeto, fora da equipa
    lucas = await _dono(db_session)  # criou o agente
    ana = await _dono(db_session)  # da equipa
    rui = await _dono(db_session)  # da equipa, silenciou o agente
    admin = await _dono(db_session)  # admin do cliente, fora da equipa
    admin.role = "admin"
    await db_session.commit()

    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    for p in (lucas, ana, rui):
        await _membro(db_session, equipa, p)
    a = await _agente(db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[servicio])
    await _silenciar(db_session, rui, a)
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204", "title": "Mesas"}]

    ex = await _correr(db_session, a)
    assert ex.status == "completed"

    avisos = await _avisos(db_session, a)
    assert avisos[lucas.id] == 1, "quem criou recebe uma vez, sem duplicado"
    assert avisos[ana.id] == 1, "a equipa recebe o achado"
    assert rui.id not in avisos, "quem silenciou o agente não recebe"
    assert semente.id not in avisos, "fora da equipa não vê os dados, não recebe"
    assert admin.id not in avisos, "admin fora da equipa: a máscara vale para o aviso"


@pytest.mark.asyncio
async def test_com_fronteira_de_projeto_o_projeto_recebe(db_session, corrida, monkeypatch):
    from src.config.settings import settings

    monkeypatch.setattr(settings, "DATA_BOUNDARY", "project")
    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    _, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    a = await _agente(db_session, lucas, scope="crew", scope_id=equipa.id, ligacoes=[servicio])
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204", "title": "Mesas"}]

    await _correr(db_session, a)

    avisos = await _avisos(db_session, a)
    assert avisos[semente.id] == 1, "com os dados no projeto, quem está no projeto vê"
    assert avisos[lucas.id] == 1


@pytest.mark.asyncio
async def test_agente_de_projeto_avisa_o_projeto(db_session, corrida):
    from src.models.space import SpaceMember

    semente = await _dono(db_session)
    lucas = await _dono(db_session)
    ana = await _dono(db_session)
    projeto, equipa, (servicio, _, _) = await _demo(db_session, semente)
    await _membro(db_session, equipa, lucas)
    db_session.add(SpaceMember(space_id=projeto.id, user_id=ana.id, role="viewer"))
    await db_session.commit()
    a = await _agente(db_session, lucas, scope="space", scope_id=projeto.id, ligacoes=[servicio])
    _MotorFalso.respostas = [{"answer": "Mesas servidas: 1.204", "title": "Mesas"}]

    await _correr(db_session, a)

    avisos = await _avisos(db_session, a)
    assert avisos[semente.id] == 1
    assert avisos[ana.id] == 1
    assert avisos[lucas.id] == 1


@pytest.mark.asyncio
async def test_agente_pessoal_so_avisa_quem_o_criou(db_session, corrida):
    from src.services.notificar_o_projeto import quem_ve_o_agente

    class _A:
        id = "x"
        scope = "personal"
        scope_id = None

    assert await quem_ve_o_agente(db_session, _A()) == []
