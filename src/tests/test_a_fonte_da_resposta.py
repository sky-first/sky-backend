# -*- coding: utf-8 -*-
"""De onde veio cada resposta — e quem pode ver isso.

> «Toda resposta é preciso a gente ter ali um botão para a gente
>  entender de onde veio os dados… A pessoa cruzar a informação e ver se
>  isso bate realmente. Isso é importantíssimo.» — Lucas, 09/10/2026

Desde 13/10/2026 a fonte guarda a DEFINIÇÃO (SQL, tabelas, contexto) e
nunca as linhas: ao abrir, o SQL volta a correr com as tabelas de quem
abre. Ver `test_dados_ao_vivo.py` para as regras da reexecução.
"""

from __future__ import annotations

import uuid

import pytest

from src.models.page import Page
from src.schemas.chat_stream import CLIENT_EVENT_TYPES, normalize_event
from src.services import dados_ao_vivo
from src.services.a_fonte_da_resposta import (
    consulta_guardada,
    definicao_da_fonte,
    fonte_em_csv,
    tem_fonte,
)
from src.tests.acceptance_helpers import bearer

LIGACAO = "11111111-2222-3333-4444-555555555555"

# ── O contrato do stream ─────────────────────────────────────────────


class TestOContrato:
    def test_as_linhas_passam_o_portao(self):
        """As linhas seguem para quem perguntou — só não se guardam."""
        assert "rows" in CLIENT_EVENT_TYPES
        ev = normalize_event(
            {
                "type": "rows",
                "columns": ["cliente", "total"],
                "rows": [["Acme", 10]],
                "truncated": False,
            }
        )
        assert ev == {
            "type": "rows",
            "columns": ["cliente", "total"],
            "rows": [["Acme", 10]],
            "truncated": False,
        }

    def test_uma_forma_estranha_nao_rebenta_o_cliente(self):
        ev = normalize_event({"type": "rows", "columns": None, "rows": "lixo", "truncated": 1})
        assert ev == {"type": "rows", "columns": [], "rows": [], "truncated": True}


# ── O que se guarda ──────────────────────────────────────────────────


class _Consulta:
    def __init__(self, sql, config):
        self.sql = sql
        self.data_sample = None
        self.configure_data = config


class TestADefinicao:
    def test_uma_resposta_sem_consulta_nao_tem_fonte(self):
        assert not tem_fonte({}, {})
        assert tem_fonte({"sql": "SELECT 1"}, {})
        assert tem_fonte({"chosen_table": "clientes"}, {})

    def test_a_definicao_tem_tabelas_sql_e_colunas_mas_nao_linhas(self):
        c = _Consulta(
            "SELECT cliente, total FROM vendas",
            {"fonte": {"tabelas": ["vendas"], "colunas": ["cliente", "total"], "total_linhas": 2}},
        )
        f = definicao_da_fonte(c)
        assert f["tabelas"] == ["vendas"]
        assert f["colunas"] == ["cliente", "total"]
        assert "linhas" not in f

    def test_o_contexto_da_pergunta_chega_a_reexecucao(self):
        c = _Consulta(
            "SELECT 1",
            {
                "fonte": {
                    "connection_id": LIGACAO,
                    "space_id": "s1",
                    "crew_id": "c1",
                    "is_personal": False,
                    "total_linhas": 7,
                }
            },
        )
        g = consulta_guardada(c)
        assert g.connection_id == LIGACAO
        assert (g.space_id, g.crew_id, g.is_personal) == ("s1", "c1", False)
        assert g.total_na_resposta == 7

    def test_uma_consulta_antiga_da_web_tira_a_ligacao_do_knowledge(self):
        c = _Consulta("SELECT 1", {"knowledge": [LIGACAO], "chosen_datasets": ["t"]})
        assert consulta_guardada(c).connection_id == LIGACAO

    def test_sem_sql_nao_ha_o_que_voltar_a_correr(self):
        assert consulta_guardada(_Consulta(None, {"fonte": {"connection_id": LIGACAO}})) is None


class TestOCsv:
    def _csv(self):
        return fonte_em_csv(
            {
                "colunas": ["projecto", "total"],
                "linhas": [["Restauración", 1234.5], ["Sem valor", None]],
            }
        )

    def test_abre_certo_no_excel_portugues(self):
        """`;` e não `,`: em Portugal e Espanha a vírgula é decimal."""
        assert self._csv().lstrip("﻿").splitlines()[0] == "projecto;total"

    def test_os_acentos_sobrevivem(self):
        texto = self._csv()
        assert texto.startswith("﻿")
        assert "Restauración" in texto

    def test_um_vazio_e_vazio_e_nao_a_palavra_none(self):
        assert "None" not in self._csv()


# ── Pelo HTTP ────────────────────────────────────────────────────────


async def _pagina(db, dono):
    pid = uuid.uuid4()
    db.add(Page(id=pid, name="Chats", type="personal", color="#FAB721", owner_id=dono))
    await db.commit()
    return pid


async def _resposta_com_fonte(db, user, page_id):
    """Uma conversa com uma resposta que tem fonte, como o stream a deixa."""
    from src.models.conversation import Conversation, Message
    from src.services.a_fonte_da_resposta import _guardar_a_fonte

    conv = Conversation(page_id=page_id, created_by=user.id, title="t")
    db.add(conv)
    await db.flush()
    msg = Message(conversation_id=conv.id, role="assistant", kind="ai_response", content="São 2.")
    db.add(msg)
    await db.flush()
    await _guardar_a_fonte(
        db,
        utilizador=user,
        mensagem=msg,
        pergunta="quantos?",
        resposta="São 2.",
        meta={"sql": "SELECT count(*) FROM clientes", "chosen_table": "clientes", "num_rows": 1},
        linhas={"columns": ["count"], "rows": [[2]], "truncated": False},
        page_id=page_id,
        contexto={"connection_id": LIGACAO, "is_personal": True},
    )
    await db.commit()
    return msg


@pytest.fixture
def motor_falso(monkeypatch):
    """O sky-ai e as permissões, a fingir: devolve 3 linhas de agora."""
    dados_ao_vivo.limpar_cache_em_memoria()
    chamadas = []

    async def _sem_redis():
        return None

    async def _tabelas(db, uid, consulta):
        return {consulta.connection_id: ["clientes"]}

    async def _rerun(self, connection_id, **kw):
        chamadas.append(kw)
        return {
            "columns": ["count"],
            "rows": [[3]],
            "row_count": 1,
            "truncated": False,
            "executed_at": "2026-10-13T12:00:00+00:00",
        }

    monkeypatch.setattr("src.config.redis.get_redis", _sem_redis)
    monkeypatch.setattr(dados_ao_vivo, "tabelas_de_quem_abre", _tabelas)
    monkeypatch.setattr("src.ai.http_client.AIServiceHTTPClient.reexecutar_sql", _rerun)
    return chamadas


@pytest.mark.asyncio
async def test_quem_pode_ler_a_conversa_ve_a_fonte_de_agora(
    async_client, test_user, valid_access_token, db_session, motor_falso
):
    from src.models.ai import AIQuery

    user = test_user["user"]
    msg = await _resposta_com_fonte(db_session, user, await _pagina(db_session, user.id))

    # Nada de linhas na base: só a definição.
    q = await db_session.get(AIQuery, msg.query_id)
    assert q.data_sample in (None, [])
    assert "rows" not in str(q.configure_data)

    r = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte", headers=bearer(valid_access_token)
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["tabelas"] == ["clientes"]
    assert corpo["linhas"] == [[3]]  # as de AGORA, não as da resposta ([[2]])
    assert corpo["ao_vivo"] is True
    assert corpo["nota"] == "dados actuais, consultados agora"
    assert corpo["total_na_resposta"] == 1
    assert motor_falso[0]["sql"].startswith("SELECT count")

    csv = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte.csv", headers=bearer(valid_access_token)
    )
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert "count" in csv.text and "3" in csv.text


@pytest.mark.asyncio
async def test_quem_nao_pode_ler_a_conversa_nao_ve_de_onde_ela_veio(
    async_client, test_user, valid_access_token, db_session, motor_falso
):
    """A fonte é conteúdo da conversa. **404, não 403**."""
    from src.models.user import User

    outro = User(
        id=uuid.uuid4(), email=f"o{uuid.uuid4().hex[:6]}@x.pt", name="Outro", password_hash="x"
    )
    db_session.add(outro)
    await db_session.commit()
    msg = await _resposta_com_fonte(db_session, outro, await _pagina(db_session, outro.id))

    for rota in (f"/api/v1/messages/{msg.id}/fonte", f"/api/v1/messages/{msg.id}/fonte.csv"):
        r = await async_client.get(rota, headers=bearer(valid_access_token))
        assert r.status_code == 404, (rota, r.status_code)
    assert motor_falso == []  # nem chegou a perguntar à fonte


@pytest.mark.asyncio
async def test_quem_perdeu_o_acesso_as_tabelas_leva_403(
    async_client, test_user, valid_access_token, db_session, motor_falso, monkeypatch
):
    async def _nada(db, uid, consulta):
        return {consulta.connection_id: []}

    monkeypatch.setattr(dados_ao_vivo, "tabelas_de_quem_abre", _nada)
    user = test_user["user"]
    msg = await _resposta_com_fonte(db_session, user, await _pagina(db_session, user.id))
    r = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte", headers=bearer(valid_access_token)
    )
    assert r.status_code == 403
    assert motor_falso == []


@pytest.mark.asyncio
async def test_uma_saudacao_nao_tem_fonte_mesmo_com_consulta(
    async_client, test_user, valid_access_token, db_session
):
    """O /ai/query cria uma linha em ai_queries para TODAS as perguntas. Sem
    tabelas nem SQL, a fonte é 404."""
    from src.models.ai import AIQuery
    from src.models.conversation import Conversation, Message

    user = test_user["user"]
    page_id = await _pagina(db_session, user.id)
    conv = Conversation(page_id=page_id, created_by=user.id, title="ola")
    db_session.add(conv)
    await db_session.flush()
    q = AIQuery(
        user_id=user.id,
        page_id=page_id,
        question="ola",
        answer="Ola!",
        configure_data={},
        status="completed",
    )
    db_session.add(q)
    await db_session.flush()
    msg = Message(
        conversation_id=conv.id, role="assistant", kind="ai_response", content="Ola!", query_id=q.id
    )
    db_session.add(msg)
    await db_session.commit()

    r = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte", headers=bearer(valid_access_token)
    )
    assert r.status_code == 404
