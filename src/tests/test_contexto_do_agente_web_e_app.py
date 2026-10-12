"""Uma resposta escrita no fio de um agente leva o contexto do agente — na web
e na app, IGUAL.

A `/ai/chat/stream` (a app) punha à frente da pergunta o agente, a pergunta
que ele repete e a discussão do fio. A web responde no mesmo fio pela
`/ai/query` (com o id da conversa no `thread_id`) e o modelo recebia uma
pergunta solta: «e agora o Norte?» não queria dizer nada.

Os testes medem o que CHEGA ao motor de IA (um falso), pelos dois caminhos,
para a mesma conversa.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.tests.acceptance_helpers import bearer

_FOCO = "Que regiões caíram mais de 20% nas vendas?"


async def _aiter(items):
    for x in items:
        yield x


async def _fio_do_agente(db, user):
    """Uma página, a conversa do agente (com uma resposta dele) e o agente."""
    from src.models.agent import Agent
    from src.models.conversation import Conversation, Message
    from src.models.page import Page

    page = Page(id=uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=user.id)
    db.add(page)
    await db.flush()
    conv = Conversation(page_id=page.id, created_by=user.id, title="Vendas por região")
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            kind="ai_response",
            content="O Sul caiu 23%.",
        )
    )
    db.add(
        Agent(
            name="Vendas por região",
            scope="personal",
            scope_id=str(user.id),
            status="active",
            monitor_type="question",
            focus=_FOCO,
            frequency="manual",
            connection_ids=[],
            created_by=user.id,
            conversation_id=conv.id,
        )
    )
    await db.commit()
    return page, conv


async def _instrucoes_pelo_stream(async_client, token, page, conv) -> str:
    captado: dict = {}

    def _captar(*a, **k):
        captado.update(k)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    with (
        patch(
            "src.services.ai_service.AIService._get_first_active_connection",
            new=AsyncMock(return_value=str(uuid4())),
        ),
        patch(
            "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
            side_effect=_captar,
        ),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "E agora o Norte?",
                "widget_id": str(uuid4()),
                "persist": True,
                "conversation_id": str(conv.id),
                "page_id": str(page.id),
            },
            headers=bearer(token),
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass
    return captado.get("instructions") or ""


class _MotorFalso:
    def __init__(self):
        self.kwargs: dict = {}

    async def process_query(self, **kw):
        self.kwargs = kw
        return {"answer": "ok", "status": "completed"}


async def _instrucoes_pela_query(db, user, page, **ids) -> str:
    from src.schemas.ai import AIQueryRequest
    from src.services.ai_service import AIService

    svc = AIService(db)
    motor = _MotorFalso()
    svc.real_ai = motor  # type: ignore[assignment]
    ligacao = str(uuid4())
    with (
        patch.object(svc, "_get_all_connections_for_user", new=AsyncMock(return_value=[ligacao])),
        patch.object(svc, "_resolve_space_id_for_connection", new=AsyncMock(return_value=None)),
        patch.object(svc, "_get_user_crew_ids", new=AsyncMock(return_value=[])),
        patch.object(svc, "_get_user_space_ids", new=AsyncMock(return_value=[])),
        patch.object(
            svc.permission_service,
            "get_authorized_tables",
            new=AsyncMock(return_value=["vendas"]),
        ),
    ):
        try:
            await svc.process_query(
                user.id,
                AIQueryRequest(
                    question="E agora o Norte?",
                    page_id=page.id,
                    is_personal=True,
                    locale="pt",
                    **ids,
                ),
            )
        except Exception:  # noqa: BLE001 — o que interessa já foi captado
            pass
    assert motor.kwargs, "o motor de IA não chegou a ser chamado"
    return motor.kwargs.get("instructions") or ""


@pytest.mark.asyncio
async def test_a_web_e_a_app_mandam_o_mesmo_contexto_do_agente(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    page, conv = await _fio_do_agente(db_session, user)

    # A web pergunta primeiro: o stream grava a pergunta no fio, e a
    # discussão a seguir já seria outra.
    pela_web = await _instrucoes_pela_query(db_session, user, page, thread_id=str(conv.id))
    pela_app = await _instrucoes_pelo_stream(
        async_client, test_user_with_tokens["access_token"], page, conv
    )

    from src.services.agent_conversation_service import instrucoes_do_agente_da_conversa

    assert _FOCO in pela_app
    assert _FOCO in pela_web
    assert "O Sul caiu 23%." in pela_web
    # O mesmo bloco, à cabeça, nos dois caminhos.
    contexto = pela_web.split("\n\n")[0]
    assert contexto.startswith('This conversation belongs to the monitoring agent "Vendas')
    assert pela_app.startswith(contexto)
    assert pela_web.startswith(
        (await instrucoes_do_agente_da_conversa(db_session, conv.id))[:200]
    )


@pytest.mark.asyncio
async def test_a_web_tambem_aceita_o_id_da_conversa_explicito(
    test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    page, conv = await _fio_do_agente(db_session, user)
    instr = await _instrucoes_pela_query(
        db_session, user, page, thread_id="sessao-do-chat-1", conversation_id=conv.id
    )
    assert _FOCO in instr


@pytest.mark.asyncio
async def test_uma_conversa_qualquer_nao_leva_contexto_de_agente(
    test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    page, _ = await _fio_do_agente(db_session, user)
    instr = await _instrucoes_pela_query(db_session, user, page, thread_id=str(uuid4()))
    assert "monitoring agent" not in instr


@pytest.mark.asyncio
async def test_quem_nao_ve_o_fio_nao_recebe_o_contexto_dele(
    test_user_with_tokens, test_second_user_with_tokens, db_session
):
    """O contexto leva a discussão do fio. Um id de conversa colado à mão não
    pode servir para a ler."""
    dono = test_user_with_tokens["user"]
    from uuid import UUID

    from src.models.user import User

    outro = await db_session.get(User, UUID(test_second_user_with_tokens["user"]["id"]))
    _, conv = await _fio_do_agente(db_session, dono)
    pagina_dele, _ = await _fio_do_agente(db_session, outro)
    instr = await _instrucoes_pela_query(
        db_session, outro, pagina_dele, thread_id=str(conv.id)
    )
    assert _FOCO not in instr
    assert "O Sul caiu 23%." not in instr
