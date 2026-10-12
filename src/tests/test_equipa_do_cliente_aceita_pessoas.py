"""Quem cria uma equipa do cliente (sem projeto) pode acrescentar-lhe gente.

`create_crew` deixa qualquer pessoa com `crews.create` fazer uma lista de
pessoas sem projeto; depois `add_crew_member` aplicava a regra do PROJETO com
`space_id=None`, não encontrava projeto e recusava todos menos o admin
(auditoria da app, 12/10/2026).
"""

from __future__ import annotations

import uuid

import pytest

from src.core.exceptions import ForbiddenError


async def _pessoa(db, role="member"):
    from src.core.security import get_password_hash
    from src.repositories.user import UserRepository

    u = await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Pessoa",
        role=role,
    )
    await db.commit()
    return u


async def _equipa_do_cliente(db, criador):
    from src.models.crew import Crew, CrewMember

    crew = Crew(name="Comercial", space_id=None, created_by=criador.id)
    db.add(crew)
    await db.flush()
    db.add(CrewMember(crew_id=crew.id, user_id=criador.id, role="owner"))
    await db.commit()
    return crew


@pytest.mark.asyncio
async def test_criador_acrescenta_e_tira_pessoas(db_session):
    from src.schemas.crew import CrewMemberCreate
    from src.services.crew_service import CrewService

    criador = await _pessoa(db_session)
    outra = await _pessoa(db_session)
    crew = await _equipa_do_cliente(db_session, criador)

    m = await CrewService(db_session).add_crew_member(
        crew.id, criador, CrewMemberCreate(user_id=outra.id, role="viewer")
    )
    assert str(m.user_id) == str(outra.id)
    await CrewService(db_session).remove_crew_member(crew.id, outra.id, criador)


@pytest.mark.asyncio
async def test_quem_nao_manda_na_equipa_continua_sem_poder(db_session):
    from src.schemas.crew import CrewMemberCreate
    from src.services.crew_service import CrewService

    criador = await _pessoa(db_session)
    intruso = await _pessoa(db_session)
    alvo = await _pessoa(db_session)
    crew = await _equipa_do_cliente(db_session, criador)

    with pytest.raises(ForbiddenError):
        await CrewService(db_session).add_crew_member(
            crew.id, intruso, CrewMemberCreate(user_id=alvo.id, role="viewer")
        )


@pytest.mark.asyncio
async def test_pela_api_o_criador_acrescenta(async_client, db_session):
    from src.core.security import create_access_token

    criador = await _pessoa(db_session)
    outra = await _pessoa(db_session)
    crew = await _equipa_do_cliente(db_session, criador)
    token = create_access_token({"sub": str(criador.id), "role": "member"})

    r = await async_client.post(
        f"/api/v1/crews/{crew.id}/members",
        json={"user_id": str(outra.id), "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_procurar_gente_para_a_equipa_esconde_quem_ja_esta(async_client, db_session):
    from src.core.security import create_access_token
    from src.repositories.user import UserRepository
    from src.core.security import get_password_hash

    criador = await _pessoa(db_session)
    crew = await _equipa_do_cliente(db_session, criador)
    await UserRepository(db_session).create(
        email="angela.ruiz@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Ángela Ruiz",
        role="member",
    )
    await db_session.commit()
    token = create_access_token({"sub": str(criador.id), "role": "member"})
    h = {"Authorization": f"Bearer {token}"}

    r = await async_client.get(
        f"/api/v1/crews/{crew.id}/pessoas-para-acrescentar?procura=angela", headers=h
    )
    assert r.status_code == 200, r.text
    assert "angela.ruiz@example.com" in [p["email"] for p in r.json()]

    r = await async_client.get(f"/api/v1/crews/{crew.id}/pessoas-para-acrescentar", headers=h)
    assert str(criador.id) not in {p["id"] for p in r.json()}
