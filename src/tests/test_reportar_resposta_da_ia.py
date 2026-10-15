"""Reportar uma resposta da IA — `POST /api/v1/ai/report` (15/10/2026).

Exigência da Google Play (*AI-Generated Content*): a app móvel tem «Reportar
resposta» em cada resposta da Sky e em cada descoberta. O que tem de ser
verdade do lado do servidor:

* fica gravado, na base do cliente, com quem, o quê, o motivo, o texto e
  quando — e com uma cópia do conteúdo (a resposta pode ser apagada depois);
* só se reporta o que se pode ver, e o que não se pode ver dá 404 (nunca 403);
* só conteúdo da IA — uma mensagem de uma pessoa não entra;
* exactamente um alvo, e só os três motivos.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models.ai import AIContentReport
from src.models.agent import AgentFinding
from src.models.space import SpaceMember
from src.tests.acceptance_helpers import bearer

URL = "/api/v1/ai/report"


async def _fio(db_session, dono_id):
    """Uma conversa pessoal de `dono_id`: pergunta → resposta da Sky."""
    from src.models.conversation import Conversation, Message
    from src.models.page import Page

    page = Page(id=uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=dono_id)
    db_session.add(page)
    await db_session.flush()
    conv = Conversation(page_id=page.id, created_by=dono_id, title="t")
    db_session.add(conv)
    await db_session.flush()
    pergunta = Message(
        conversation_id=conv.id, role="user", kind="question", content="Quantos?", user_id=dono_id
    )
    db_session.add(pergunta)
    await db_session.flush()
    resposta = Message(
        conversation_id=conv.id,
        role="assistant",
        kind="ai_response",
        content="São 12 clientes.",
        parent_message_id=pergunta.id,
    )
    db_session.add(resposta)
    await db_session.commit()
    return pergunta.id, resposta.id


async def _denuncias(db_session):
    return (await db_session.execute(select(AIContentReport))).scalars().all()


@pytest.mark.asyncio
async def test_reportar_uma_resposta_fica_gravado(
    async_client, test_user, valid_access_token, db_session
):
    user = test_user["user"]
    _, resposta = await _fio(db_session, user.id)

    r = await async_client.post(
        URL,
        json={
            "message_id": str(resposta),
            "reason": "offensive",
            "text": "  Linguagem imprópria. ",
        },
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["id"] and corpo["created_at"]

    [linha] = await _denuncias(db_session)
    assert linha.user_id == user.id
    assert linha.message_id == resposta
    assert linha.finding_id is None
    assert linha.motivo == "offensive"
    assert linha.texto == "Linguagem imprópria."
    assert linha.conteudo == "São 12 clientes."
    assert linha.created_at is not None


@pytest.mark.asyncio
async def test_o_texto_e_opcional(async_client, test_user, valid_access_token, db_session):
    _, resposta = await _fio(db_session, test_user["user"].id)
    r = await async_client.post(
        URL,
        json={"message_id": str(resposta), "reason": "wrong", "text": "   "},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201
    [linha] = await _denuncias(db_session)
    assert linha.texto is None


@pytest.mark.asyncio
async def test_resposta_de_uma_conversa_alheia_e_404(
    async_client, test_user, valid_access_token, db_session
):
    """Uma conversa pessoal de outra pessoa: nem se reporta, nem se confirma
    que existe."""
    from src.repositories.user import UserRepository

    outro = await UserRepository(db_session).create(
        email=f"outro-{uuid4().hex[:6]}@exemplo.pt", password_hash="x", name="Outro", role="member"
    )
    await db_session.commit()
    _, resposta = await _fio(db_session, outro.id)

    r = await async_client.post(
        URL,
        json={"message_id": str(resposta), "reason": "other"},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 404
    assert await _denuncias(db_session) == []


@pytest.mark.asyncio
async def test_mensagem_inexistente_e_404(async_client, valid_access_token, db_session):
    r = await async_client.post(
        URL,
        json={"message_id": str(uuid4()), "reason": "other"},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_so_se_reportam_respostas_da_ia(
    async_client, test_user, valid_access_token, db_session
):
    pergunta, _ = await _fio(db_session, test_user["user"].id)
    r = await async_client.post(
        URL,
        json={"message_id": str(pergunta), "reason": "offensive"},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 422
    assert await _denuncias(db_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corpo",
    [
        {"reason": "wrong"},  # nenhum alvo
        {"message_id": str(uuid4()), "finding_id": str(uuid4()), "reason": "wrong"},  # dois
        {"message_id": str(uuid4()), "reason": "spam"},  # motivo desconhecido
        {"message_id": str(uuid4()), "reason": "other", "text": "x" * 2001},  # texto longo
    ],
)
async def test_pedidos_mal_formados_sao_422(async_client, valid_access_token, corpo):
    r = await async_client.post(URL, json=corpo, headers=bearer(valid_access_token))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sem_sessao_e_401(async_client):
    r = await async_client.post(URL, json={"message_id": str(uuid4()), "reason": "other"})
    assert r.status_code in (401, 403)


def _achado(db, space_id, title="Margem caiu"):
    f = AgentFinding(
        agent_id=None,
        source="scan",
        space_id=space_id,
        agent_name="Autonomous scan",
        type="insight",
        severity="med",
        title=title,
        description="Caiu 3,4 pontos no Norte.",
        series=[],
        stat_tiles=[],
        viz_kind="big_number",
    )
    db.add(f)
    return f


@pytest.mark.asyncio
async def test_reportar_uma_descoberta(async_client, test_user, valid_access_token, db_session):
    space = uuid4()
    db_session.add(SpaceMember(user_id=test_user["user"].id, space_id=space, role="member"))
    f = _achado(db_session, space)
    await db_session.commit()
    await db_session.refresh(f)

    r = await async_client.post(
        URL, json={"finding_id": str(f.id), "reason": "wrong"}, headers=bearer(valid_access_token)
    )
    assert r.status_code == 201, r.text
    [linha] = await _denuncias(db_session)
    assert linha.finding_id == f.id and linha.message_id is None
    assert "Margem caiu" in linha.conteudo


@pytest.mark.asyncio
async def test_descoberta_fora_do_ambito_e_404(async_client, valid_access_token, db_session):
    f = _achado(db_session, uuid4(), title="segredo")
    await db_session.commit()
    await db_session.refresh(f)
    r = await async_client.post(
        URL,
        json={"finding_id": str(f.id), "reason": "offensive"},
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 404
    assert await _denuncias(db_session) == []
