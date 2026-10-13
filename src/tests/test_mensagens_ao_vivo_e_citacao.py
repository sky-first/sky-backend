"""Editar, apagar e reagir chegam à sala ao vivo; responder/citar no stream.

Paridade 13/10 (#26-#29): corrigir ou apagar uma mensagem só se via nos outros
aparelhos ao recarregar, e o `/ai/chat/stream` não aceitava `parent_message_id`.

Eventos na sala `/ws/chat/{page_id}`:
- `message.updated` → `MessageResponse` da mensagem corrigida;
- `message.deleted` → `{conversation_id, message_id, message_ids}`;
- `message.reaction` → `{conversation_id, message_id, reactions}` (já existia).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.tests.acceptance_helpers import bearer

_BROADCAST = "src.services.message_service.broadcast_event_nowait"
_CONN = "src.services.ai_service.AIService._get_first_active_connection"
_STREAM = "src.ai.http_client.AIServiceHTTPClient.stream_query_connection"


async def _aiter(items):
    for x in items:
        yield x


async def _fio(db_session, user):
    """Página + conversa com: pergunta (minha) → resposta da Sky, e uma
    resposta de OUTRA pessoa que cita a minha pergunta."""
    from src.models.conversation import Conversation, Message
    from src.models.page import Page

    page = Page(id=uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=user.id)
    db_session.add(page)
    await db_session.flush()
    conv = Conversation(page_id=page.id, created_by=user.id, title="t")
    db_session.add(conv)
    await db_session.flush()
    pergunta = Message(
        conversation_id=conv.id, role="user", kind="question", content="Quantos?", user_id=user.id
    )
    db_session.add(pergunta)
    await db_session.flush()
    resposta = Message(
        conversation_id=conv.id,
        role="assistant",
        kind="ai_response",
        content="12",
        parent_message_id=pergunta.id,
    )
    citacao = Message(
        conversation_id=conv.id,
        role="user",
        kind="comment",
        content="Concordo",
        user_id=None,
        parent_message_id=pergunta.id,
    )
    db_session.add_all([resposta, citacao])
    await db_session.commit()
    return {
        "page": page.id,
        "conv": conv.id,
        "pergunta": pergunta.id,
        "resposta": resposta.id,
        "citacao": citacao.id,
    }


def _eventos(bc, tipo):
    return [c.args for c in bc.call_args_list if c.args[1] == tipo]


async def _apagada(db_session, mid):
    from src.models.conversation import Message

    db_session.expire_all()
    return (await db_session.get(Message, mid)).deleted_at is not None


@pytest.mark.asyncio
async def test_apagar_anuncia_message_deleted_com_a_resposta(
    async_client, test_user_with_tokens, db_session
):
    ids = await _fio(db_session, test_user_with_tokens["user"])
    with patch(_BROADCAST) as bc:
        r = await async_client.delete(
            f"/api/v1/messages/{ids['pergunta']}",
            headers=bearer(test_user_with_tokens["access_token"]),
        )
    assert r.status_code == 200, r.text
    assert r.json()["apagadas"] == 2
    (ev,) = _eventos(bc, "message.deleted")
    sala, _, payload = ev
    assert sala == str(ids["page"])
    assert payload["conversation_id"] == str(ids["conv"])
    assert payload["message_id"] == str(ids["pergunta"])
    assert set(payload["message_ids"]) == {str(ids["pergunta"]), str(ids["resposta"])}


@pytest.mark.asyncio
async def test_apagar_nao_leva_as_palavras_de_quem_citou(
    async_client, test_user_with_tokens, db_session
):
    """`parent_message_id` também liga uma citação. Só as respostas da Sky
    vão atrás; o que outra pessoa escreveu fica."""
    ids = await _fio(db_session, test_user_with_tokens["user"])
    with patch(_BROADCAST):
        await async_client.delete(
            f"/api/v1/messages/{ids['pergunta']}",
            headers=bearer(test_user_with_tokens["access_token"]),
        )
    assert await _apagada(db_session, ids["resposta"])
    assert not await _apagada(db_session, ids["citacao"])


@pytest.mark.asyncio
async def test_editar_anuncia_updated_e_a_resposta_que_saiu(
    async_client, test_user_with_tokens, db_session
):
    ids = await _fio(db_session, test_user_with_tokens["user"])
    with patch(_BROADCAST) as bc:
        r = await async_client.patch(
            f"/api/v1/messages/{ids['pergunta']}",
            json={"content": "Quantos em Lisboa?"},
            headers=bearer(test_user_with_tokens["access_token"]),
        )
    assert r.status_code == 200, r.text
    tipos = [c.args[1] for c in bc.call_args_list]
    assert tipos == ["message.updated", "message.deleted"]
    (_, _, msg), (_, _, apagadas) = (c.args for c in bc.call_args_list)
    assert msg["id"] == str(ids["pergunta"])
    assert msg["content"] == "Quantos em Lisboa?"
    assert msg["author_name"]
    assert apagadas["message_ids"] == [str(ids["resposta"])]
    # A citação de outra pessoa não sai.
    assert not await _apagada(db_session, ids["citacao"])


@pytest.mark.asyncio
async def test_reagir_anuncia_message_reaction(async_client, test_user_with_tokens, db_session):
    ids = await _fio(db_session, test_user_with_tokens["user"])
    with patch(_BROADCAST) as bc:
        r = await async_client.post(
            f"/api/v1/conversations/{ids['conv']}/messages/{ids['resposta']}/reactions",
            json={"emoji": "👍"},
            headers=bearer(test_user_with_tokens["access_token"]),
        )
    assert r.status_code == 200, r.text
    (ev,) = _eventos(bc, "message.reaction")
    assert ev[2]["message_id"] == str(ids["resposta"])
    assert ev[2]["reactions"] == {"👍": [str(test_user_with_tokens["user"].id)]}


# ─── /ai/chat/stream · parent_message_id ────────────────────────────────────


async def _perguntar(async_client, token, payload):
    with (
        patch(_CONN, new=AsyncMock(return_value=str(uuid4()))),
        patch(
            _STREAM, side_effect=lambda *a, **k: _aiter(['data: {"type":"chunk","content":"ok"}'])
        ),
    ):
        async with async_client.stream(
            "POST", "/api/v1/ai/chat/stream", json=payload, headers=bearer(token)
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass


async def _pergunta_gravada(db_session, conv_id, texto):
    from sqlalchemy import select

    from src.models.conversation import Message

    db_session.expire_all()
    return (
        await db_session.execute(
            select(Message).where(Message.conversation_id == conv_id, Message.content == texto)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_stream_grava_a_pergunta_como_resposta_a_mensagem_citada(
    async_client, test_user_with_tokens, db_session
):
    ids = await _fio(db_session, test_user_with_tokens["user"])
    await _perguntar(
        async_client,
        test_user_with_tokens["access_token"],
        {
            "message": "E em Lisboa?",
            "widget_id": str(uuid4()),
            "persist": True,
            "conversation_id": str(ids["conv"]),
            "page_id": str(ids["page"]),
            "parent_message_id": str(ids["resposta"]),
        },
    )
    q = await _pergunta_gravada(db_session, ids["conv"], "E em Lisboa?")
    assert q.parent_message_id == ids["resposta"]


@pytest.mark.asyncio
async def test_stream_ignora_citacao_de_outra_conversa(
    async_client, test_user_with_tokens, db_session
):
    """Uma citação nunca liga duas conversas."""
    user = test_user_with_tokens["user"]
    a = await _fio(db_session, user)
    b = await _fio(db_session, user)
    await _perguntar(
        async_client,
        test_user_with_tokens["access_token"],
        {
            "message": "Cruzada?",
            "widget_id": str(uuid4()),
            "persist": True,
            "conversation_id": str(a["conv"]),
            "page_id": str(a["page"]),
            "parent_message_id": str(b["resposta"]),
        },
    )
    q = await _pergunta_gravada(db_session, a["conv"], "Cruzada?")
    assert q.parent_message_id is None


@pytest.mark.asyncio
async def test_stream_ignora_citacao_inexistente(async_client, test_user_with_tokens, db_session):
    ids = await _fio(db_session, test_user_with_tokens["user"])
    await _perguntar(
        async_client,
        test_user_with_tokens["access_token"],
        {
            "message": "Fantasma?",
            "widget_id": str(uuid4()),
            "persist": True,
            "conversation_id": str(ids["conv"]),
            "page_id": str(ids["page"]),
            "parent_message_id": str(uuid4()),
        },
    )
    q = await _pergunta_gravada(db_session, ids["conv"], "Fantasma?")
    assert q.parent_message_id is None
    assert isinstance(q.id, UUID)
