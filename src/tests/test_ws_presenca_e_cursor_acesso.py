"""Presença e cursores: o mesmo portão do ``/ws/chat`` (#751).

Os dois WebSockets só verificavam o token. Qualquer pessoa com um token
válido — de outra equipa, ou de outro cliente — via quem estava online numa
equipa (e aparecia online lá) e seguia os cursores de qualquer sala cujo id
conhecesse. Agora: cliente pelo ``tid``, revogação do logout, e a pertença à
sala. Recusa = 1008; token mau ou revogado = 4001.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def _ws_usa_a_base_do_teste(db_session, monkeypatch):
    """Os WS abrem a sua própria sessão (não passam por Depends)."""
    from contextlib import asynccontextmanager

    from src.api.v1 import cursor, presence

    @asynccontextmanager
    async def _sessao(_ctx):
        yield db_session

    monkeypatch.setattr(presence, "_open_session", _sessao)
    monkeypatch.setattr(cursor, "_open_session", _sessao)


async def _pessoa(db_session: AsyncSession, email: str):
    user = await UserRepository(db_session).create(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role="user",
    )
    await db_session.commit()
    return user


def _token(user) -> str:
    return create_access_token({"sub": str(user.id)})


def _fecha_com(client, url):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_text()
    return exc.value.code


async def _projeto_com_equipa(db_session: AsyncSession, dono):
    from src.models.crew import Crew, CrewMember

    space = Space(name="Projeto", created_by=dono.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    crew = Crew(name="Financeiro", space_id=space.id, created_by=dono.id)
    db_session.add(crew)
    await db_session.commit()
    await db_session.refresh(crew)
    db_session.add(CrewMember(crew_id=crew.id, user_id=dono.id, role="owner"))
    db_session.add(SpaceMember(space_id=space.id, user_id=dono.id, role="owner"))
    await db_session.commit()
    return space, crew


# ─── /presence/{crew_id} ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_presenca_recusa_quem_nao_e_da_equipa(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    dono = test_user_with_tokens["user"]
    space, crew = await _projeto_com_equipa(db_session, dono)

    # De fora de tudo.
    intruso = await _pessoa(db_session, "intruso@example.com")
    assert _fecha_com(client, f"/api/v1/presence/{crew.id}?token={_token(intruso)}") == 1008

    # Do projeto, mas não DESTA equipa — a presença é da equipa.
    so_projeto = await _pessoa(db_session, "projeto@example.com")
    db_session.add(SpaceMember(space_id=space.id, user_id=so_projeto.id, role="viewer"))
    await db_session.commit()
    assert _fecha_com(client, f"/api/v1/presence/{crew.id}?token={_token(so_projeto)}") == 1008


@pytest.mark.asyncio
async def test_presenca_deixa_entrar_o_membro_da_equipa(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    from src.models.crew import CrewMember

    dono = test_user_with_tokens["user"]
    _space, crew = await _projeto_com_equipa(db_session, dono)
    membro = await _pessoa(db_session, "membro@example.com")
    db_session.add(CrewMember(crew_id=crew.id, user_id=membro.id, role="member"))
    await db_session.commit()

    with client.websocket_connect(f"/api/v1/presence/{crew.id}?token={_token(membro)}") as ws:
        # Primeiro chega o próprio `presence_update` (o broadcast inclui quem
        # entrou), depois o `presence_init`.
        tipos = []
        init = None
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            tipos.append(msg["type"])
            if msg["type"] == "presence_init":
                init = msg
                break
        assert init is not None, tipos
        assert str(membro.id) in init["online_user_ids"]


@pytest.mark.asyncio
async def test_presenca_equipa_inexistente_ou_id_invalido_fecha_1008(
    client: TestClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    nada = "00000000-0000-0000-0000-000000000000"
    assert _fecha_com(client, f"/api/v1/presence/{nada}?token={token}") == 1008
    assert _fecha_com(client, f"/api/v1/presence/nao-e-um-uuid?token={token}") == 1008


@pytest.mark.asyncio
async def test_presenca_token_invalido_ou_revogado_fecha_4001(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    dono = test_user_with_tokens["user"]
    _space, crew = await _projeto_com_equipa(db_session, dono)
    assert _fecha_com(client, f"/api/v1/presence/{crew.id}?token=x") == 4001

    # Logout revoga os tokens emitidos antes — o dono da equipa fica de fora.
    async def _revogado(_uid, _iat):
        return True

    monkeypatch.setattr("src.core.token_blocklist.is_token_revoked", _revogado)
    token = test_user_with_tokens["access_token"]
    assert _fecha_com(client, f"/api/v1/presence/{crew.id}?token={token}") == 4001


# ─── /cursor/{context_id} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cursor_recusa_quem_nao_e_da_sala(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    dono = test_user_with_tokens["user"]
    space, crew = await _projeto_com_equipa(db_session, dono)
    intruso = await _pessoa(db_session, "intruso2@example.com")
    t = _token(intruso)
    assert _fecha_com(client, f"/api/v1/cursor/{crew.id}?token={t}") == 1008
    assert _fecha_com(client, f"/api/v1/cursor/{space.id}?token={t}") == 1008

    # Página privada de outra pessoa.
    page = Page(name="Privada", type="personal", color="#3b82f6", owner_id=dono.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    assert _fecha_com(client, f"/api/v1/cursor/{page.id}?token={t}") == 1008


@pytest.mark.asyncio
async def test_cursor_deixa_entrar_membro_da_equipa_do_projeto_e_da_pagina(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    from src.models.crew import CrewMember

    dono = test_user_with_tokens["user"]
    space, crew = await _projeto_com_equipa(db_session, dono)

    # Sala de equipa → membro da equipa.
    da_equipa = await _pessoa(db_session, "equipa@example.com")
    db_session.add(CrewMember(crew_id=crew.id, user_id=da_equipa.id, role="member"))
    # Sala de projeto → membro do projeto.
    do_projeto = await _pessoa(db_session, "proj@example.com")
    db_session.add(SpaceMember(space_id=space.id, user_id=do_projeto.id, role="viewer"))
    await db_session.commit()

    with client.websocket_connect(f"/api/v1/cursor/{crew.id}?token={_token(da_equipa)}"):
        pass
    with client.websocket_connect(f"/api/v1/cursor/{space.id}?token={_token(do_projeto)}"):
        pass

    # Membro do projeto NÃO entra na sala da equipa.
    assert _fecha_com(client, f"/api/v1/cursor/{crew.id}?token={_token(do_projeto)}") == 1008

    # Página do próprio.
    page = Page(name="Minha", type="personal", color="#3b82f6", owner_id=dono.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    with client.websocket_connect(
        f"/api/v1/cursor/{page.id}?token={test_user_with_tokens['access_token']}"
    ):
        pass


@pytest.mark.asyncio
async def test_cursor_id_invalido_1008_e_token_invalido_4001(
    client: TestClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    assert _fecha_com(client, f"/api/v1/cursor/some-context-id?token={token}") == 1008
    assert _fecha_com(client, "/api/v1/cursor/some-context-id?token=x") == 4001


@pytest.mark.asyncio
async def test_cursor_token_revogado_fecha_4001(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession, monkeypatch
):
    dono = test_user_with_tokens["user"]
    _space, crew = await _projeto_com_equipa(db_session, dono)

    async def _revogado(_uid, _iat):
        return True

    monkeypatch.setattr("src.core.token_blocklist.is_token_revoked", _revogado)
    token = test_user_with_tokens["access_token"]
    assert _fecha_com(client, f"/api/v1/cursor/{crew.id}?token={token}") == 4001
