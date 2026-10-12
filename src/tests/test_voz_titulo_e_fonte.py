"""A resposta falada guarda-se como a escrita: o mesmo nome e a mesma fonte.

Há três caminhos que gravam respostas — o stream (app), o `/ai/query` +
ask-ai (web) e a voz. Os dois primeiros davam à conversa o nome da primeira
frase (`_titulo_a_partir_de`) e guardavam a fonte (tabelas, SQL, linhas)
para o «ver a fonte». A voz cortava os primeiros 80 caracteres em bruto e
não guardava fonte nenhuma: a mesma pergunta, dita, aparecia com outro nome
e sem botão.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import uuid

import pytest
from sqlalchemy import select

from src.services import voice_session_service as vss
from src.services.message_service import _titulo_a_partir_de

_META = {"sql": "SELECT count(*) FROM clientes", "chosen_table": "clientes", "num_rows": 1}
_LINHAS = {"type": "rows", "columns": ["count"], "rows": [[46]], "truncated": False}


# ── O nome ────────────────────────────────────────────────────────────


def _turno(role, text):
    from src.schemas.voice import VoiceTurn

    return VoiceTurn(role=role, text=text)


def test_o_nome_e_o_mesmo_da_conversa_escrita():
    longa = (
        "Quanto faturámos em Setembro nas lojas do Norte comparado com o "
        "mesmo mês do ano passado e porquê"
    )
    assert vss._title_from([_turno("user", longa)]) == _titulo_a_partir_de(longa)
    # Cortado numa palavra e com reticências — não a meio de «comparado».
    assert vss._title_from([_turno("user", longa)]).endswith("…")
    assert len(vss._title_from([_turno("user", longa)])) <= 61


def test_a_primeira_frase_chega():
    t = vss._title_from([_turno("user", "Quantos clientes temos? E em Lisboa, quantos?")])
    assert t == "Quantos clientes temos?"


def test_sem_pergunta_fica_o_nome_por_omissao():
    assert vss._title_from([_turno("sky", "Olá")]) == "Voice conversation"


# ── O colector ────────────────────────────────────────────────────────


def test_a_fonte_fica_no_ponto_da_conversa_em_que_correu():
    def _sessao():
        turnos = ["user"]
        vss.abrir_fontes_da_sessao(lambda: len(turnos))
        vss.registar_fonte("quantos?", _META, _LINHAS)
        return vss.fontes_da_sessao()

    # Um contexto novo, como uma sessão de voz no seu próprio socket.
    fontes = contextvars.copy_context().run(_sessao)
    assert len(fontes) == 1
    assert fontes[0].turno == 1
    assert fontes[0].meta["sql"].startswith("SELECT")


def test_sem_sessao_aberta_nao_se_regista_nada():
    def _fora():
        vss.registar_fonte("quantos?", _META, _LINHAS)
        return vss.fontes_da_sessao()

    assert contextvars.Context().run(_fora) == []


# ── A gravação ────────────────────────────────────────────────────────


async def _pagina(db, dono_id):
    from src.models.page import Page

    pid = uuid.uuid4()
    db.add(Page(id=pid, name="Chats", type="personal", color="#FAB721", owner_id=dono_id))
    await db.commit()
    return pid


@pytest.mark.asyncio
async def test_a_resposta_falada_guarda_a_fonte_na_mensagem_certa(test_user, db_session):
    from src.models.ai import AIQuery
    from src.models.conversation import Conversation, Message
    from src.schemas.voice import VoiceSessionCreate

    user = test_user["user"]
    pid = await _pagina(db_session, user.id)
    turnos = [
        _turno("user", "Olá Sky"),
        _turno("sky", "Olá! Em que posso ajudar?"),
        _turno("user", "Quantos clientes temos?"),
        _turno("sky", "Temos 46 clientes."),
    ]
    fonte = vss.FonteFalada(turno=3, pergunta="Quantos clientes temos?", meta=_META, linhas=_LINHAS)

    conv_id, titulo, n = await vss.VoiceSessionService(db_session).persist(
        user,
        VoiceSessionCreate(page_id=pid, turns=turnos, duration_ms=4000),
        fontes=[fonte],
    )
    assert n == 4
    assert titulo == "Olá Sky"

    msgs = (
        (
            await db_session.execute(
                select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    # Só a resposta que veio da consulta tem fonte — a saudação não.
    assert [m.query_id is not None for m in msgs] == [False, False, False, True]
    consulta = await db_session.get(AIQuery, msgs[3].query_id)
    assert consulta.sql == _META["sql"]
    assert consulta.data_sample == [[46]]
    assert consulta.configure_data["fonte"]["tabelas"] == ["clientes"]
    assert consulta.question == "Quantos clientes temos?"
    assert (await db_session.get(Conversation, conv_id)).title == "Olá Sky"


@pytest.mark.asyncio
async def test_o_cliente_nao_consegue_mandar_fontes(
    async_client, test_user, valid_access_token, db_session
):
    """O `POST /voice/sessions` aceita turnos, não fontes. Uma fonte é SQL e
    linhas com o nosso selo — vir do cliente era deixá-lo inventá-las."""
    from src.models.conversation import Message
    from src.tests.acceptance_helpers import bearer

    pid = await _pagina(db_session, test_user["user"].id)
    r = await async_client.post(
        "/api/v1/voice/sessions",
        json={
            "page_id": str(pid),
            "turns": [
                {"role": "user", "text": "quantos?"},
                {"role": "sky", "text": "46", "meta": _META, "rows": _LINHAS},
            ],
            "fontes": [{"turno": 1, "pergunta": "x", "meta": _META, "linhas": _LINHAS}],
        },
        headers=bearer(valid_access_token),
    )
    assert r.status_code == 201, r.text
    msgs = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(r.json()["conversation_id"]))
        )
    ).scalars().all()
    assert all(m.query_id is None for m in msgs)


# ── A consulta da voz regista a fonte ────────────────────────────────


@pytest.mark.asyncio
async def test_a_consulta_da_voz_regista_a_fonte_que_o_motor_mandou(monkeypatch):
    from src.api.v1 import voice as voice_module

    class _Servico:
        async def _get_all_connections_for_space(self, user_id, space_id):
            return ["conn-1"]

        async def _get_first_active_connection_for_space(self, user_id, space_id, q=None):
            return "conn-1"

        async def _get_user_crew_ids(self, user_id, space_id=None, *, all_spaces=False):
            return []

    @contextlib.asynccontextmanager
    async def _sessao(_ctx):
        yield object()

    monkeypatch.setattr(
        "src.config.tenant_connection_manager.tenant_connection_manager.session_for", _sessao
    )
    monkeypatch.setattr("src.services.ai_service.AIService", lambda _db: _Servico())

    class _Motor:
        def stream_query_connection(self, **kw):
            async def _linhas():
                yield "data: " + json.dumps({"type": "meta", "meta": _META})
                yield "data: " + json.dumps(_LINHAS)
                yield "data: " + json.dumps({"type": "chunk", "content": "Temos 46."})

            return _linhas()

    monkeypatch.setattr("src.ai.http_client.AIServiceHTTPClient", _Motor)

    class _U:
        id = "user-1"
        preferences = {}

    async def _sessao_de_voz():
        turnos = ["user"]
        vss.abrir_fontes_da_sessao(lambda: len(turnos))
        resposta = await voice_module._voice_answer(
            _U(), "pagina-1", "Quantos clientes temos?", ctx=object(), locale="pt",
            space_id="projeto-1",
        )
        return resposta, vss.fontes_da_sessao()

    import asyncio

    resposta, fontes = await asyncio.create_task(_sessao_de_voz())
    assert resposta == "Temos 46."
    assert len(fontes) == 1
    assert fontes[0].pergunta == "Quantos clientes temos?"
    assert fontes[0].meta == _META
    assert fontes[0].linhas["rows"] == [[46]]
    assert fontes[0].turno == 1
