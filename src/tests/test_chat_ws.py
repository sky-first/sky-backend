"""Chat WebSocket integration tests (chat-threads-master-plan PR7).

Exercises the in-memory ChatRelay broadcast path: a peer subscribes
to /ws/chat/{page_id}, the test fires HTTP write actions (post
comment, post a question, open a change-request), and the test
asserts the right event envelopes arrive on the listening socket.

Uses the `client` fixture from conftest.py so the dependency-
overridden TestClient is reused. TestClient supports WebSocket via
`websocket_connect()`.

Important: TestClient's WebSocket is a *sync* context, but the BE
relay is async (it does asyncio.create_task to fan out). The test
asserts via `ws.receive_text(timeout=...)` which blocks the test
thread until the relay flushes — so timing is deterministic.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.models.widget import Widget
from src.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def _ws_usa_a_base_do_teste(db_session, monkeypatch):
    """O WS abre a sua própria sessão (não passa por Depends); nos testes tem
    de ser a mesma base em memória que os pedidos HTTP usam."""
    from contextlib import asynccontextmanager

    from src.api.v1 import chat_ws

    @asynccontextmanager
    async def _sessao(_ctx):
        yield db_session

    monkeypatch.setattr(chat_ws, "_open_session", _sessao)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_user(db_session: AsyncSession, email: str):
    repo = UserRepository(db_session)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role="user",
    )
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_chat_ws_broadcasts_message_created(
    client: TestClient,
    test_user_with_tokens: dict,
    db_session: AsyncSession,
):
    """Posting a message on a conversation should push a
    `message.created` event to every WS peer subscribed to the page.
    """
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]

    page = Page(name="P", type="personal", color="#3b82f6", owner_id=user.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    r_conv = client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=auth_header(token)
    )
    assert r_conv.status_code == 201, r_conv.text
    conv_id = r_conv.json()["id"]

    with client.websocket_connect(
        f"/api/v1/ws/chat/{page.id}?token={token}"
    ) as ws:
        r_msg = client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"role": "user", "content": "hello"},
            headers=auth_header(token),
        )
        assert r_msg.status_code == 201, r_msg.text

        # **Lê-se até encontrar**, e não a primeira trama.
        #
        # O que este teste garante é que o evento *chega* a quem está
        # subscrito — é o que a explicação lá em cima diz. Exigir que seja o
        # primeiro envelope é exigir uma ordem que ninguém prometeu: o relay
        # também empurra `conversation.created`, e qual deles chega primeiro
        # depende de tempos. Apanhado a 26/08, com o teste a falhar por
        # receber `conversation.created` num sítio onde nada tinha mudado.
        #
        # Se o evento **não** chegar, isto continua a falhar — no limite das
        # tentativas ou no tempo de espera da própria ligação.
        envelope = None
        for _ in range(5):
            envelope = json.loads(ws.receive_text())
            if envelope["type"] == "message.created":
                break
        assert envelope is not None
        assert envelope["type"] == "message.created"
        assert envelope["payload"]["content"] == "hello"
        assert envelope["payload"]["conversation_id"] == conv_id


@pytest.mark.asyncio
async def test_chat_ws_rejects_invalid_token(client: TestClient):
    """Connections with no/invalid token should be closed with 4001."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/ws/chat/00000000-0000-0000-0000-000000000000?token=not-a-jwt"
        ) as ws:
            ws.receive_text()


@pytest.mark.asyncio
async def test_chat_ws_broadcasts_change_request_created(
    client: TestClient,
    test_user_with_tokens: dict,
    db_session: AsyncSession,
):
    """change_request.created should fan out to peers on the page."""
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=user.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    space = Space(name="S", created_by=user.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="owner"))
    other = await create_user(db_session, "other@example.com")
    db_session.add(SpaceMember(space_id=space.id, user_id=other.id, role="editor"))
    await db_session.commit()

    widget = Widget(
        page_id=page.id,
        type="chart",
        title="Sales",
        position={"x": 0, "y": 0},
        size={"width": 400, "height": 300},
        data={},
        created_by=user.id,
    )
    db_session.add(widget)
    await db_session.commit()
    await db_session.refresh(widget)

    r_conv = client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id)},
        headers=auth_header(token),
    )
    conv_id = r_conv.json()["id"]

    with client.websocket_connect(
        f"/api/v1/ws/chat/{page.id}?token={token}"
    ) as ws:
        other_token = create_access_token({"sub": str(other.id)})

        rc = client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"role": "user", "kind": "comment", "content": "fix axis"},
            headers=auth_header(other_token),
        )
        assert rc.status_code == 201, rc.text
        msg_id = rc.json()["id"]

        ws.receive_text()  # drain message.created

        rcr = client.post(
            "/api/v1/change-requests",
            json={
                "widget_id": str(widget.id),
                "conversation_id": conv_id,
                "message_id": msg_id,
                "content": "fix axis",
            },
            headers=auth_header(other_token),
        )
        assert rcr.status_code == 201, rcr.text

        raw = ws.receive_text()
        envelope = json.loads(raw)
        assert envelope["type"] == "change_request.created"
        assert envelope["payload"]["widget_id"] == str(widget.id)


# ─── Acesso à sala (segurança) ───────────────────────────────────────────────
#
# O WS aceitava qualquer token válido para QUALQUER página: um membro de outra
# equipa (ou de outro cliente) ouvia as mensagens, os achados e os widgets de
# uma página cujo id conhecesse. A regra agora é a do REST
# (`PageService.get_page`): dono, membro da página, da equipa ou do projeto.


def _fecha_com(client, url):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_text()
    return exc.value.code


@pytest.mark.asyncio
async def test_chat_ws_recusa_quem_nao_tem_acesso_a_pagina(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    dono = test_user_with_tokens["user"]
    page = Page(name="Privada", type="personal", color="#3b82f6", owner_id=dono.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    intruso = await create_user(db_session, "intruso@example.com")
    token_intruso = create_access_token({"sub": str(intruso.id)})

    code = _fecha_com(client, f"/api/v1/ws/chat/{page.id}?token={token_intruso}")
    assert code == 1008


@pytest.mark.asyncio
async def test_chat_ws_recusa_membro_de_outra_equipa(
    client: TestClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    from src.models.crew import Crew, CrewMember

    dono = test_user_with_tokens["user"]
    space = Space(name="S", created_by=dono.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    crew = Crew(name="Financeiro", space_id=space.id, created_by=dono.id)
    db_session.add(crew)
    await db_session.commit()
    await db_session.refresh(crew)
    db_session.add(CrewMember(crew_id=crew.id, user_id=dono.id, role="owner"))
    page = Page(
        name="Sala", type="team", color="#3b82f6", owner_id=dono.id,
        space_id=space.id, crew_id=crew.id,
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    # Membro do projeto, mas NÃO da equipa dona da página.
    fora = await create_user(db_session, "fora@example.com")
    db_session.add(SpaceMember(space_id=space.id, user_id=fora.id, role="viewer"))
    await db_session.commit()
    token_fora = create_access_token({"sub": str(fora.id)})
    assert _fecha_com(client, f"/api/v1/ws/chat/{page.id}?token={token_fora}") == 1008

    # Quem é da equipa entra.
    dentro = await create_user(db_session, "dentro@example.com")
    db_session.add(CrewMember(crew_id=crew.id, user_id=dentro.id, role="member"))
    await db_session.commit()
    token_dentro = create_access_token({"sub": str(dentro.id)})
    with client.websocket_connect(f"/api/v1/ws/chat/{page.id}?token={token_dentro}"):
        pass


@pytest.mark.asyncio
async def test_chat_ws_recusa_pagina_inexistente_e_id_invalido(
    client: TestClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    assert (
        _fecha_com(client, f"/api/v1/ws/chat/00000000-0000-0000-0000-000000000000?token={token}")
        == 1008
    )
    assert _fecha_com(client, f"/api/v1/ws/chat/nao-e-um-uuid?token={token}") == 1008


@pytest.mark.asyncio
async def test_chat_ws_token_invalido_fecha_4001(client: TestClient):
    assert _fecha_com(client, "/api/v1/ws/chat/00000000-0000-0000-0000-000000000000?token=x") == 4001
