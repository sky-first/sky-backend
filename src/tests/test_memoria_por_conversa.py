"""Uma conversa, uma memória.

O `sky-ai` guarda o histórico por ``thread_id``. A ``/ai/chat/stream`` (a app)
e a voz não mandavam nenhum, e o motor caía em pessoa + ligação: todas as
conversas da mesma pessoa sobre a mesma ligação partilhavam a memória. O
``thread_id`` que a app manda era deitado fora pelo Pydantic.

Estes testes medem o ``thread_id`` que CHEGA ao motor (um falso):

* duas conversas da mesma pessoa, na mesma ligação → fios diferentes;
* a mesma conversa, dois turnos → o mesmo fio;
* web (``/ai/query``) e app (``/ai/chat/stream``) na mesma conversa → o mesmo;
* sem conversa nem fio → nada vai, como antes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.tests.acceptance_helpers import bearer

LIGACAO = str(uuid4())


async def _aiter(items):
    for x in items:
        yield x


async def _pagina_e_conversas(db, user, n=2):
    from src.models.conversation import Conversation
    from src.models.page import Page

    page = Page(id=uuid4(), name="Chats", type="personal", color="#FAB721", owner_id=user.id)
    db.add(page)
    await db.flush()
    convs = []
    for i in range(n):
        c = Conversation(page_id=page.id, created_by=user.id, title=f"Conversa {i}")
        db.add(c)
        convs.append(c)
    await db.commit()
    return page, convs


async def _fio_pelo_stream(async_client, token, page, **extra):
    """O ``thread_id`` que a ``/ai/chat/stream`` manda ao motor."""
    captado: dict = {}

    def _captar(*a, **k):
        captado.update(k)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    corpo = {
        "message": "E agora o Norte?",
        "widget_id": str(uuid4()),
        "page_id": str(page.id),
        **extra,
    }
    with (
        patch(
            "src.services.ai_service.AIService._get_first_active_connection",
            new=AsyncMock(return_value=LIGACAO),
        ),
        patch(
            "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
            side_effect=_captar,
        ),
    ):
        async with async_client.stream(
            "POST", "/api/v1/ai/chat/stream", json=corpo, headers=bearer(token)
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass
    assert captado, "o motor de IA não chegou a ser chamado"
    assert captado.get("connection_id") == LIGACAO
    return captado.get("thread_id")


class _MotorFalso:
    def __init__(self):
        self.kwargs: dict = {}

    async def process_query(self, **kw):
        self.kwargs = kw
        return {"answer": "ok", "status": "completed"}


async def _fio_pela_query(db, user, page, **ids):
    from src.schemas.ai import AIQueryRequest
    from src.services.ai_service import AIService

    svc = AIService(db)
    motor = _MotorFalso()
    svc.real_ai = motor  # type: ignore[assignment]
    with (
        patch.object(svc, "_get_all_connections_for_user", new=AsyncMock(return_value=[LIGACAO])),
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
    return motor.kwargs.get("thread_id")


# ─── /ai/chat/stream (a app) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duas_conversas_da_mesma_pessoa_nao_partilham_memoria(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page, (a, b) = await _pagina_e_conversas(db_session, user)

    fio_a = await _fio_pelo_stream(async_client, token, page, conversation_id=str(a.id))
    fio_b = await _fio_pelo_stream(async_client, token, page, conversation_id=str(b.id))

    assert fio_a and fio_b
    assert fio_a != fio_b, "duas conversas na mesma ligação partilhavam a memória"
    assert str(a.id) in fio_a and str(b.id) in fio_b


@pytest.mark.asyncio
async def test_a_mesma_conversa_mantem_a_memoria_entre_turnos(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page, (a, _b) = await _pagina_e_conversas(db_session, user)

    t1 = await _fio_pelo_stream(async_client, token, page, conversation_id=str(a.id))
    t2 = await _fio_pelo_stream(
        async_client, token, page, conversation_id=str(a.id), thread_id=str(a.id)
    )
    assert t1 == t2


@pytest.mark.asyncio
async def test_conversa_nova_tem_fio_proprio(async_client, test_user_with_tokens, db_session):
    """``persist`` sem ``conversation_id``: nasce uma conversa, e a memória
    começa vazia — não herda a da última conversa da pessoa."""
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page, (a, _b) = await _pagina_e_conversas(db_session, user)

    antiga = await _fio_pelo_stream(async_client, token, page, conversation_id=str(a.id))
    nova1 = await _fio_pelo_stream(async_client, token, page, persist=True)
    nova2 = await _fio_pelo_stream(async_client, token, page, persist=True)
    assert nova1 and nova2
    assert len({antiga, nova1, nova2}) == 3


@pytest.mark.asyncio
async def test_o_thread_id_da_app_ja_nao_e_deitado_fora(
    async_client, test_user_with_tokens, db_session
):
    """Sem ``persist`` (sem conversa gravada), o ``thread_id`` da app conta."""
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page, _ = await _pagina_e_conversas(db_session, user)

    s1 = await _fio_pelo_stream(async_client, token, page, thread_id="sessao-1")
    s1b = await _fio_pelo_stream(async_client, token, page, thread_id="sessao-1")
    s2 = await _fio_pelo_stream(async_client, token, page, thread_id="sessao-2")
    assert s1 == s1b
    assert s1 != s2
    assert s1.endswith(":fio:sessao-1"), "o fio vai com o cliente à frente, nunca cru"


@pytest.mark.asyncio
async def test_sem_conversa_nem_fio_fica_como_antes(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    token = test_user_with_tokens["access_token"]
    page, _ = await _pagina_e_conversas(db_session, user)
    assert await _fio_pelo_stream(async_client, token, page) is None


@pytest.mark.asyncio
async def test_conversa_alheia_nao_empresta_a_memoria(
    async_client, test_user_with_tokens, db_session
):
    """Saber o id de uma conversa que não se pode ver não dá a memória dela."""
    from src.core.security import create_access_token, get_password_hash
    from src.repositories.user import UserRepository

    dono = test_user_with_tokens["user"]
    page, (privada, _b) = await _pagina_e_conversas(db_session, dono)
    fio_do_dono = await _fio_pelo_stream(
        async_client, test_user_with_tokens["access_token"], page, conversation_id=str(privada.id)
    )

    outro = await UserRepository(db_session).create(
        email="outro@example.com",
        password_hash=get_password_hash("password123"),
        name="outro",
        role="user",
    )
    await db_session.commit()
    token_outro = create_access_token({"sub": str(outro.id)})
    pagina_do_outro, _ = await _pagina_e_conversas(db_session, outro, n=0)
    fio_do_outro = await _fio_pelo_stream(
        async_client, token_outro, pagina_do_outro, thread_id=str(privada.id)
    )
    assert fio_do_outro != fio_do_dono
    # E nem pelo `conversation_id` (que, não visível, abre conversa nova).
    fio_do_outro2 = await _fio_pelo_stream(
        async_client, token_outro, pagina_do_outro, conversation_id=str(privada.id)
    )
    assert fio_do_outro2 != fio_do_dono


# ─── /ai/query (a web) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_e_app_na_mesma_conversa_partilham_o_fio(
    async_client, test_user_with_tokens, db_session
):
    user = test_user_with_tokens["user"]
    page, (a, b) = await _pagina_e_conversas(db_session, user)

    pela_web = await _fio_pela_query(db_session, user, page, thread_id=str(a.id))
    pela_app = await _fio_pelo_stream(
        async_client, test_user_with_tokens["access_token"], page, conversation_id=str(a.id)
    )
    assert pela_web == pela_app

    outra_pela_web = await _fio_pela_query(db_session, user, page, conversation_id=b.id)
    assert outra_pela_web != pela_web


@pytest.mark.asyncio
async def test_query_sem_fio_continua_a_usar_o_id_da_pergunta(test_user_with_tokens, db_session):
    user = test_user_with_tokens["user"]
    page, _ = await _pagina_e_conversas(db_session, user)
    fio = await _fio_pela_query(db_session, user, page)
    assert fio and ":" not in fio  # o id da própria pergunta, sem memória


# ─── A regra em si ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_fio_unidade(test_user_with_tokens, db_session):
    from src.services.fio_da_conversa import resolver_fio

    user = test_user_with_tokens["user"]
    _page, (a, b) = await _pagina_e_conversas(db_session, user)

    fa = await resolver_fio(db_session, user, conversation_id=a.id, tenant_slug="acme")
    assert fa == f"acme:conv:{a.id}"
    # O id da conversa no thread_id dá a MESMA chave (web = app).
    assert await resolver_fio(db_session, user, thread_id=str(a.id), tenant_slug="acme") == fa
    assert await resolver_fio(db_session, user, conversation_id=b.id, tenant_slug="acme") != fa
    # O cliente faz parte da chave: dois clientes nunca partilham.
    assert await resolver_fio(db_session, user, conversation_id=a.id, tenant_slug="outro") != fa
    assert await resolver_fio(db_session, user, tenant_slug="acme") is None


@pytest.mark.asyncio
async def test_fio_da_voz_isola_cada_sessao():
    from src.core.tenant_context import TenantContext
    from src.services.fio_da_conversa import fio_da_voz

    class _Ctx:
        slug = "acme"

    ctx = _Ctx()
    s1 = await fio_da_voz(ctx, object(), None, "s1")
    s2 = await fio_da_voz(ctx, object(), None, "s2")
    assert s1 != s2
    assert s1 == await fio_da_voz(ctx, object(), None, "s1")
    assert s1.startswith("acme:")
    assert TenantContext  # importável — o ctx real tem `slug`


def test_a_voz_manda_o_fio_ao_motor():
    """O ``_voice_answer`` aceita o fio e passa-o ao motor; a cascata e o
    Sonic dão-lho."""
    import inspect

    from src.api.v1 import voice
    from src.services import voz_ponte_sonic, voz_sessao_sonic

    assert "thread_id" in inspect.signature(voice._voice_answer).parameters  # noqa: SLF001
    assert "thread_id=thread_id" in inspect.getsource(voice._voice_answer)  # noqa: SLF001
    assert "fio_da_voz" in inspect.getsource(voice.voice_session_ws)
    assert "thread_id=thread_id" in inspect.getsource(voz_ponte_sonic.ferramenta_do_cliente)
    assert "fio_da_voz" in inspect.getsource(voz_sessao_sonic.servir)


def test_chat_message_request_aceita_thread_id():
    from src.schemas.ai import ChatMessageRequest

    r = ChatMessageRequest(message="x", widget_id=uuid4(), thread_id="t-1")
    assert r.thread_id == "t-1"
