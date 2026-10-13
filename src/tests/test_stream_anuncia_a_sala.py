"""O `/ai/chat/stream` avisa a sala quando grava o turno.

Regressão do #692: a web passou a perguntar pelo stream, que gravava pergunta e
resposta sem `message.created`. O `ask-ai` antigo emitia os dois eventos; quem
estava a ver a página (na web ou na app) só via o turno ao recarregar.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.tests.acceptance_helpers import bearer

_CONN = "src.services.ai_service.AIService._get_first_active_connection"
_STREAM = "src.ai.http_client.AIServiceHTTPClient.stream_query_connection"
_BROADCAST = "src.services.message_service.broadcast_event_nowait"


async def _aiter(items):
    for x in items:
        yield x


async def _pagina_e_conversa(db_session, user):
    from src.models.conversation import Conversation
    from src.models.page import Page

    page = Page(id=uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=user.id)
    db_session.add(page)
    await db_session.flush()
    conv = Conversation(page_id=page.id, created_by=user.id, title=None)
    db_session.add(conv)
    await db_session.commit()
    return page, conv


async def _perguntar(async_client, token, payload, engine):
    with (
        patch(_CONN, new=AsyncMock(return_value=str(uuid4()))),
        patch(_STREAM, side_effect=lambda *a, **k: _aiter(engine)),
    ):
        async with async_client.stream(
            "POST", "/api/v1/ai/chat/stream", json=payload, headers=bearer(token)
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass


@pytest.mark.asyncio
async def test_stream_emite_message_created_da_pergunta_e_da_resposta(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    page, conv = await _pagina_e_conversa(db_session, user)
    engine = ['data: {"type": "chunk", "content": "São 12."}', 'data: {"type": "done"}']

    with patch(_BROADCAST) as bc:
        await _perguntar(
            async_client,
            test_user_with_tokens["access_token"],
            {
                "message": "Quantos clientes?",
                "widget_id": str(uuid4()),
                "persist": True,
                "conversation_id": str(conv.id),
                "page_id": str(page.id),
            },
            engine,
        )

    criadas = [c for c in bc.call_args_list if c.args[1] == "message.created"]
    assert len(criadas) == 2, bc.call_args_list
    (sala_q, _, pergunta), (sala_r, _, resposta) = (c.args for c in criadas)
    assert sala_q == sala_r == str(page.id)
    # Pergunta primeiro, com autor; depois a resposta da Sky, sem autor.
    assert pergunta["role"] == "user" and pergunta["kind"] == "question"
    assert pergunta["content"] == "Quantos clientes?"
    assert pergunta["conversation_id"] == str(conv.id)
    assert pergunta["user_id"] == str(user.id)
    assert pergunta["author_name"]
    assert resposta["role"] == "assistant" and resposta["kind"] == "ai_response"
    assert resposta["content"] == "São 12."
    assert resposta["parent_message_id"] == pergunta["id"]
    assert resposta["author_name"] is None
    # O mesmo envelope do `ask-ai` (MessageResponse): os clientes já o leem.
    for campo in ("id", "created_at", "reactions", "origin"):
        assert campo in pergunta and campo in resposta


@pytest.mark.asyncio
async def test_motor_falhou_so_a_pergunta_e_anunciada(
    async_client, test_user_with_tokens, db_session
):
    """Sem resposta gravada, não se anuncia uma resposta — só a pergunta."""
    user = test_user_with_tokens["user"]
    page, conv = await _pagina_e_conversa(db_session, user)
    engine = [
        'data: {"type": "chunk", "content": "Tem "}',
        'data: {"type": "error", "message": "engine down", "code": "engine_failed"}',
    ]
    with patch(_BROADCAST) as bc:
        await _perguntar(
            async_client,
            test_user_with_tokens["access_token"],
            {
                "message": "Quantos?",
                "widget_id": str(uuid4()),
                "persist": True,
                "conversation_id": str(conv.id),
                "page_id": str(page.id),
            },
            engine,
        )
    criadas = [c.args[2] for c in bc.call_args_list if c.args[1] == "message.created"]
    assert [m["role"] for m in criadas] == ["user"]


@pytest.mark.asyncio
async def test_sem_persist_nao_anuncia_nada(async_client, test_user_with_tokens):
    with patch(_BROADCAST) as bc:
        await _perguntar(
            async_client,
            test_user_with_tokens["access_token"],
            {"message": "olá", "widget_id": str(uuid4())},
            ['data: {"type": "chunk", "content": "olá"}'],
        )
    assert not [c for c in bc.call_args_list if c.args[1] == "message.created"]


@pytest.mark.asyncio
async def test_falha_do_aviso_nao_parte_o_turno(async_client, test_user_with_tokens, db_session):
    """O relay a rebentar não pode custar a resposta nem o `conversation_id`."""
    from sqlalchemy import select

    from src.models.conversation import Message

    user = test_user_with_tokens["user"]
    page, conv = await _pagina_e_conversa(db_session, user)
    conv_id = conv.id
    with patch(_BROADCAST, side_effect=RuntimeError("relay em baixo")):
        await _perguntar(
            async_client,
            test_user_with_tokens["access_token"],
            {
                "message": "Quantos?",
                "widget_id": str(uuid4()),
                "persist": True,
                "conversation_id": str(conv.id),
                "page_id": str(page.id),
            },
            ['data: {"type": "chunk", "content": "12"}'],
        )
    db_session.expire_all()
    rows = (
        (await db_session.execute(select(Message).where(Message.conversation_id == conv_id)))
        .scalars()
        .all()
    )
    assert sorted(m.role for m in rows) == ["assistant", "user"]
