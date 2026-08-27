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
