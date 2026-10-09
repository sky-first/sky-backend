# -*- coding: utf-8 -*-
"""De onde veio cada resposta — e quem pode ver isso.

> «Toda resposta é preciso a gente ter ali um botão para a gente
>  entender de onde veio os dados… A pessoa cruzar a informação e ver se
>  isso bate realmente. Isso é importantíssimo.» — Lucas, 09/10/2026
"""
from __future__ import annotations

import uuid

import pytest

from src.models.page import Page
from src.schemas.chat_stream import CLIENT_EVENT_TYPES, normalize_event
from src.services.a_fonte_da_resposta import fonte_em_csv, fonte_para_mostrar, tem_fonte
from src.tests.acceptance_helpers import bearer

# ── O contrato do stream ─────────────────────────────────────────────


class TestOContrato:
    def test_as_linhas_passam_o_portao(self):
        """O motor já as mandava; o portão é que as deitava fora."""
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
        """A forma fecha-se aqui: listas sempre listas, truncado sempre bool."""
        ev = normalize_event({"type": "rows", "columns": None, "rows": "lixo", "truncated": 1})
        assert ev == {"type": "rows", "columns": [], "rows": [], "truncated": True}


# ── O que se guarda, e o que se mostra ───────────────────────────────


class _Consulta:
    def __init__(self, sql, linhas, fonte):
        self.sql = sql
        self.data_sample = linhas
        self.configure_data = {"fonte": fonte}


class TestAFonte:
    def test_uma_resposta_sem_consulta_nao_tem_fonte(self):
        """Uma saudação não consultou nada. Mostrar um botão vazio era pior."""
        assert not tem_fonte({}, {})
        assert tem_fonte({"sql": "SELECT 1"}, {})
        assert tem_fonte({"chosen_table": "clientes"}, {})

    def test_mostra_as_tabelas_o_sql_e_as_linhas(self):
        c = _Consulta(
            "SELECT cliente, total FROM vendas",
            [["Acme", 10], ["Delta", 7]],
            {
                "tabelas": ["vendas"],
                "colunas": ["cliente", "total"],
                "total_linhas": 2,
                "truncado": False,
            },
        )
        f = fonte_para_mostrar(c)
        assert f["tabelas"] == ["vendas"]
        assert f["sql"].startswith("SELECT")
        assert f["linhas"] == [["Acme", 10], ["Delta", 7]]
        assert f["truncado"] is False

    def test_quando_o_motor_cortou_a_fonte_diz_quanto_havia(self):
        """Mostrar 200 linhas sem dizer que eram 5000 fazia a pessoa cruzar
        um pedaço como se fosse o todo — o contrário do que isto quer."""
        c = _Consulta(
            "SELECT *",
            [[i] for i in range(200)],
            {"colunas": ["n"], "total_linhas": 5000, "truncado": True},
        )
        f = fonte_para_mostrar(c)
        assert f["truncado"] is True
        assert f["total_linhas"] == 5000
        assert len(f["linhas"]) == 200


class TestOCsv:
    def _csv(self):
        c = _Consulta(
            "SELECT 1",
            [["Restauración", 1234.5], ["Sem valor", None]],
            {"colunas": ["projecto", "total"]},
        )
        return fonte_em_csv(c)

    def test_abre_certo_no_excel_portugues(self):
        """`;` e não `,`: em Portugal e Espanha a vírgula é decimal, e um
        CSV com vírgulas abre tudo numa coluna só."""
        primeira = self._csv().lstrip("﻿").splitlines()[0]
        assert primeira == "projecto;total"

    def test_os_acentos_sobrevivem(self):
        """Sem BOM o Excel lê UTF-8 como Latin-1: «Restauración» vira lixo."""
        texto = self._csv()
        assert texto.startswith("﻿")
        assert "Restauración" in texto

    def test_um_vazio_e_vazio_e_nao_a_palavra_none(self):
        assert "None" not in self._csv()


# ── Quem pode ver ────────────────────────────────────────────────────


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
    )
    await db.commit()
    return msg


@pytest.mark.asyncio
async def test_quem_pode_ler_a_conversa_ve_a_fonte(
    async_client, test_user, valid_access_token, db_session
):
    user = test_user["user"]
    msg = await _resposta_com_fonte(db_session, user, await _pagina(db_session, user.id))

    r = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte", headers=bearer(valid_access_token)
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["tabelas"] == ["clientes"]
    assert "SELECT" in corpo["sql"]
    assert corpo["linhas"] == [[2]]

    csv = await async_client.get(
        f"/api/v1/messages/{msg.id}/fonte.csv", headers=bearer(valid_access_token)
    )
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert "count" in csv.text


@pytest.mark.asyncio
async def test_quem_nao_pode_ler_a_conversa_nao_ve_de_onde_ela_veio(
    async_client, test_user, valid_access_token, db_session
):
    """A fonte é conteúdo da conversa. **404, não 403**: dizer «existe mas
    não podes» já é dizer que existe."""
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


# ── O caminho da web (/ai/query) ─────────────────────────────────────


class _ConsultaDaWeb:
    """Como o /ai/query deixa a consulta: linhas como objectos, tabelas em
    configure_data.chosen_datasets, e nenhuma chave `fonte`."""

    def __init__(self, sql, linhas, config):
        self.sql = sql
        self.data_sample = linhas
        self.configure_data = config


class TestOCaminhoDaWeb:
    def test_linhas_em_objectos_viram_tabela(self):
        """Sem isto a fonte de uma resposta da web nao tinha linhas — o que
        a pessoa quer cruzar."""
        c = _ConsultaDaWeb(
            "SELECT region, ingresos FROM facturacion",
            [{"region": "Sur", "ingresos": 214300}, {"region": "Norte", "ingresos": 79600}],
            {"chosen_datasets": ["facturacion"]},
        )
        f = fonte_para_mostrar(c)
        assert f["colunas"] == ["region", "ingresos"]
        assert f["linhas"] == [["Sur", 214300], ["Norte", 79600]]
        assert f["tabelas"] == ["facturacion"]
        assert f["total_linhas"] == 2

    def test_uma_coluna_que_falta_numa_linha_nao_encolhe_a_tabela(self):
        c = _ConsultaDaWeb("SELECT 1", [{"a": 1}, {"a": 2, "b": 3}], {})
        f = fonte_para_mostrar(c)
        assert f["colunas"] == ["a", "b"]
        assert f["linhas"] == [[1, None], [2, 3]]

    def test_o_csv_de_uma_resposta_da_web_leva_as_linhas(self):
        c = _ConsultaDaWeb("SELECT 1", [{"region": "Sur", "ingresos": 1}], {})
        csv = fonte_em_csv(c)
        assert "region;ingresos" in csv
        assert "Sur;1" in csv


@pytest.mark.asyncio
async def test_uma_saudacao_nao_tem_fonte_mesmo_com_consulta(
    async_client, test_user, valid_access_token, db_session
):
    """O /ai/query cria uma linha em ai_queries para TODAS as perguntas, e a
    web liga-a a resposta. Sem tabelas, SQL nem linhas, a fonte e 404 — e o
    painel diz que nao ha fonte, em vez de abrir vazio."""
    from src.models.ai import AIQuery
    from src.models.conversation import Conversation, Message

    user = test_user["user"]
    page_id = await _pagina(db_session, user.id)
    conv = Conversation(page_id=page_id, created_by=user.id, title="ola")
    db_session.add(conv)
    await db_session.flush()
    q = AIQuery(
        user_id=user.id, page_id=page_id, question="ola", answer="Ola!",
        configure_data={}, data_sample=[], status="completed",
    )
    db_session.add(q)
    await db_session.flush()
    msg = Message(
        conversation_id=conv.id, role="assistant", kind="ai_response", content="Ola!", query_id=q.id
    )
    db_session.add(msg)
    await db_session.commit()

    r = await async_client.get(f"/api/v1/messages/{msg.id}/fonte", headers=bearer(valid_access_token))
    assert r.status_code == 404
