"""Um @ na PRIMEIRA pergunta de um fio (ask-ai) também avisa.

A web faz a primeira pergunta de um fio por `POST /conversations/{id}/ask-ai`,
que não aceitava `mentions`: o @ ficava no texto e a pessoa nunca sabia. As
mensagens seguintes (`createMessage`) já notificavam. O caminho agora é o
mesmo — `_notificar_mencionados`, notificação na língua de quem recebe +
push.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.tests.acceptance_helpers import bearer


async def _conversa(db, dono_id):
    from src.models.conversation import Conversation
    from src.models.page import Page

    page = Page(id=uuid.uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=dono_id)
    db.add(page)
    await db.flush()
    conv = Conversation(page_id=page.id, created_by=dono_id, title=None)
    db.add(conv)
    await db.commit()
    return conv


async def _pessoa(db):
    from src.core.security import get_password_hash
    from src.repositories.user import UserRepository

    u = await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Paulo",
        role="member",
    )
    u.preferences = {"language": "pt"}
    await db.commit()
    return u


async def _avisos_de(db, user_id):
    from src.models.notification import Notification

    db.expire_all()
    return (
        (await db.execute(select(Notification).where(Notification.user_id == user_id)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_ask_ai_com_mencao_cria_a_notificacao(
    async_client, test_user, valid_access_token, db_session
):
    conv = await _conversa(db_session, test_user["user"].id)
    conv_id = conv.id
    paulo_id = (await _pessoa(db_session)).id

    r = await async_client.post(
        f"/api/v1/conversations/{conv.id}/ask-ai",
        json={
            "question": "@Paulo quanto faturámos em Setembro?",
            "ai_answer": "Faturámos 12.400 €.",
            "mentions": [str(paulo_id)],
        },
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201, r.text

    avisos = await _avisos_de(db_session, paulo_id)
    assert len(avisos) == 1
    assert avisos[0].entity_id == str(conv_id)
    assert "conversation=" in (avisos[0].deep_link or "")


@pytest.mark.asyncio
async def test_sem_mencoes_ninguem_e_avisado(
    async_client, test_user, valid_access_token, db_session
):
    conv = await _conversa(db_session, test_user["user"].id)
    paulo_id = (await _pessoa(db_session)).id

    r = await async_client.post(
        f"/api/v1/conversations/{conv.id}/ask-ai",
        json={"question": "quanto faturámos?", "ai_answer": "12.400 €."},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201, r.text
    assert await _avisos_de(db_session, paulo_id) == []


@pytest.mark.asyncio
async def test_mencionar_se_a_si_proprio_nao_avisa(
    async_client, test_user, valid_access_token, db_session
):
    conv = await _conversa(db_session, test_user["user"].id)
    eu = test_user["user"].id
    r = await async_client.post(
        f"/api/v1/conversations/{conv.id}/ask-ai",
        json={
            "question": "nota para mim",
            "ai_answer": "ok",
            "mentions": [str(eu)],
        },
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201, r.text
    assert await _avisos_de(db_session, eu) == []
