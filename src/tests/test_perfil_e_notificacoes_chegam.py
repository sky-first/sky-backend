"""O que a app grava passa a ser lido (auditoria da app, 12/10/2026).

1. Perfil: ``nickname`` e ``response_preferences`` gravavam-se e ninguém os
   lia. Agora chegam ao motor nas ``instructions`` do ``/ai/chat/stream``.
2. «Notificaciones · Encendido» lia ``notifications.enabled``, que ninguém
   escrevia. ``GET /settings`` devolve agora o estado real do modo
   concentração.
3. Uma pergunta à Sky com ``mentions`` avisa as pessoas (o stream não tinha o
   campo).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from src.services.preferencias_de_resposta import instrucoes_de_resposta, juntar


async def _aiter(items):
    for x in items:
        yield x


def test_sem_preferencias_nao_acrescenta_nada():
    assert instrucoes_de_resposta(None) == ""
    assert instrucoes_de_resposta({"theme": "dark"}) == ""
    assert juntar("base", {}) == "base"


def test_apelido_e_preferencias_vao_para_as_instrucoes_e_sao_cortados():
    bloco = instrucoes_de_resposta(
        {"nickname": "  Luquinhas ", "response_preferences": "Respostas curtas, em tópicos. " * 50}
    )
    assert '"Luquinhas"' in bloco
    assert "Respostas curtas, em tópicos." in bloco
    # Cortado: um texto enorme seria contexto pago em cada pergunta.
    assert len(bloco) < 900
    assert juntar("CONTEXTO", {"nickname": "Lu"}).startswith("CONTEXTO\n\n")


async def _prefs(db, user_id, prefs):
    from src.models.user import User

    await db.execute(update(User).where(User.id == user_id).values(preferences=prefs))
    await db.commit()


@pytest.mark.asyncio
async def test_o_stream_leva_o_perfil_ao_motor(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    user = test_user_with_tokens["user"]
    await _prefs(
        db_session, user.id, {"nickname": "Lu", "response_preferences": "Sempre em tópicos"}
    )
    capturado: dict = {}

    def _impl(*args, **kwargs):
        capturado.update(kwargs)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    with patch(
        "src.services.ai_service.AIService._get_first_active_connection",
        new=AsyncMock(return_value=str(uuid4())),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection", side_effect=_impl
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={"message": "Quanto vendemos?", "widget_id": str(uuid4())},
            headers={"Authorization": f"Bearer {test_user_with_tokens['access_token']}"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_bytes():
                pass

    instr = capturado.get("instructions") or ""
    assert '"Lu"' in instr
    assert "Sempre em tópicos" in instr


@pytest.mark.asyncio
async def test_settings_diz_a_verdade_sobre_o_modo_concentracao(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}

    r = await async_client.get("/api/v1/settings", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["notifications"]["enabled"] is True
    assert r.json()["notifications"]["paused"] is False

    r = await async_client.post(
        "/api/v1/notifications/preferences/pause", json={"paused": True}, headers=h
    )
    assert r.status_code == 200, r.text

    r = await async_client.get("/api/v1/settings", headers=h)
    assert r.json()["notifications"]["enabled"] is False
    assert r.json()["notifications"]["paused"] is True

    r = await async_client.get("/api/v1/notifications/preferences/pause", headers=h)
    assert r.json() == {"paused": True, "enabled": False}


@pytest.mark.asyncio
async def test_pergunta_a_sky_com_mencao_avisa(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    from src.core.security import get_password_hash
    from src.models.notification import Notification
    from src.repositories.user import UserRepository

    outra = await UserRepository(db_session).create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Ángela Ruiz",
        role="member",
    )
    await db_session.commit()
    outra_id = outra.id

    with patch(
        "src.services.ai_service.AIService._get_first_active_connection",
        new=AsyncMock(return_value=str(uuid4())),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=lambda *a, **k: _aiter(['data: {"type": "chunk", "content": "ok"}']),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "@Ángela vê isto: quanto vendemos?",
                "widget_id": str(uuid4()),
                "persist": True,
                "mentions": [str(outra_id)],
            },
            headers={"Authorization": f"Bearer {test_user_with_tokens['access_token']}"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_bytes():
                pass

    db_session.expire_all()
    avisos = (
        (await db_session.execute(select(Notification).where(Notification.user_id == outra_id)))
        .scalars()
        .all()
    )
    assert [a.type for a in avisos] == ["comment_mention"]
