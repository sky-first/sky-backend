# -*- coding: utf-8 -*-
"""Nunca guardamos as linhas do cliente — e reexecutar respeita quem abre.

> «Nunca guardamos as linhas do cliente. O ver a fonte, os widgets e os
>  achados voltam a correr o SQL contra a fonte do cliente quando se
>  abrem.» — Lucas, 13/10/2026

Estes testes fixam o COMPORTAMENTO, não o código:

1. o que se grava não tem linhas, venha de que caminho vier;
2. a reexecução usa as tabelas de QUEM ABRE (outra equipa → 403);
3. a cache é curta (≤ 5 min) e por pessoa;
4. a limpeza só conta sem `--aplicar`, e aplicar duas vezes é seguro.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import text

from src.models.agent import AgentExecution, AgentFinding
from src.models.ai import AIQuery
from src.models.page import Page
from src.models.widget import Widget
from src.services import dados_ao_vivo as dav
from src.tests.acceptance_helpers import bearer

LIG = "aaaaaaaa-2222-3333-4444-bbbbbbbbbbbb"
LINHAS = [{"regiao": "Norte", "total": 10}, {"regiao": "Sul", "total": 7}]


def _tem_linhas(valor) -> bool:
    """Procura, em qualquer profundidade, um valor que só as linhas trazem."""
    return "Norte" in json.dumps(valor, default=str)


# ── 1. Nada do que se grava traz linhas ──────────────────────────────


class TestNadaSeGravaComLinhas:
    def test_widget_de_grafico_fica_com_a_definicao(self):
        w = Widget(
            type="chart",
            data={"question": "q", "sql": "SELECT 1", "data": LINHAS, "mapping": {"x": "regiao"}},
        )
        assert not _tem_linhas(w.data)
        assert w.data["sql"] == "SELECT 1" and w.data["mapping"] == {"x": "regiao"}

    def test_widget_kpi_tabela_e_insight(self):
        kpi = Widget(type="kpi", data={"value": "Norte", "data": LINHAS, "answer": "São 17."})
        tab = Widget(type="table", data={"columns": ["regiao"], "rows": LINHAS})
        ins = Widget(
            type="insight",
            data={"content": {"chart_block": {"chartType": "bar", "data": LINHAS}}},
        )
        for w in (kpi, tab, ins):
            assert not _tem_linhas(w.data), w.type
        assert kpi.data["answer"] == "São 17."  # o texto gerado fica
        assert ins.data["content"]["chart_block"]["chartType"] == "bar"

    def test_widget_de_texto_nao_perde_nada(self):
        w = Widget(type="text", data={"content": "Olá Norte"})
        assert w.data == {"content": "Olá Norte"}

    def test_demo_marcado_fica(self):
        w = Widget(type="chart", data={"demo": True, "data": LINHAS})
        assert _tem_linhas(w.data)

    def test_a_api_nao_aceita_a_marca_de_demo(self):
        from src.schemas.widget import WidgetCreate, WidgetUpdate

        c = WidgetCreate(
            page_id=uuid.uuid4(),
            type="chart",
            title="t",
            position={"x": 0, "y": 0},
            size={"width": 1, "height": 1},
            data={"demo": True, "data": LINHAS},
        )
        assert "demo" not in c.data
        assert not _tem_linhas(Widget(type="chart", data=c.data).data)
        assert "demo" not in WidgetUpdate(data={"demo": True}).data

    def test_ai_query_nunca_guarda_data_sample(self):
        q = AIQuery(question="q", configure_data={}, data_sample=LINHAS)
        assert q.data_sample is None
        q.data_sample = LINHAS
        assert q.data_sample is None

    def test_achado_guarda_a_definicao_e_nao_a_serie(self):
        f = AgentFinding(
            type="insight",
            title="t",
            description="d",
            rows={
                "columns": ["regiao", "total"],
                "data": [["Norte", 10]],
                "sql": "SELECT 1",
                "connection_id": LIG,
            },
            series=[{"t": "Norte", "v": 10}],
        )
        assert not _tem_linhas(f.rows) and f.series == []
        assert f.rows == {
            "columns": ["regiao", "total"],
            "sql": "SELECT 1",
            "connection_id": LIG,
            "row_count": 1,
        }

    def test_execucao_so_guarda_numeros(self):
        e = AgentExecution(result_payload={"rows": LINHAS, "schema": []})
        assert e.result_payload == {"schema": [], "row_count": 2}


# ── 2. Reexecutar com as tabelas de QUEM ABRE ────────────────────────


@pytest.fixture
def sem_redis(monkeypatch):
    async def _nenhum():
        return None

    monkeypatch.setattr("src.config.redis.get_redis", _nenhum)
    dav.limpar_cache_em_memoria()
    yield
    dav.limpar_cache_em_memoria()


@pytest.fixture
def motor(monkeypatch):
    chamadas = []

    async def _rerun(self, connection_id, **kw):
        chamadas.append(kw)
        return {
            "columns": ["regiao", "total"],
            "rows": [["Norte", 10]],
            "row_count": 1,
            "truncated": False,
            "executed_at": "2026-10-13T12:00:00+00:00",
        }

    async def _seg(**kw):
        return None

    monkeypatch.setattr("src.ai.http_client.AIServiceHTTPClient.reexecutar_sql", _rerun)
    monkeypatch.setattr("src.services.security_config_builder.build_security_config", _seg)
    return chamadas


class _Pessoa:
    def __init__(self):
        self.id = uuid.uuid4()


def _permissoes(monkeypatch, equipas_da_pessoa, tabelas_por_equipa, membro_do_projeto=False):
    """As equipas de quem abre e o que cada equipa dá — a fingir, mas pela
    MESMA função (`tabelas_de_quem_abre`) que a reexecução usa."""
    from src.services.ai_service import AIService
    from src.services.permission_service import PermissionService

    async def _equipas(self, user_id, space_id=None, *, all_spaces=False):
        return list(equipas_da_pessoa)

    async def _membro(self, user_id, space_id):
        return membro_do_projeto

    async def _tabelas(
        self, user_id, connection_id, space_id=None, crew_ids=None, is_personal=False
    ):
        saida = []
        for c in crew_ids or []:
            saida.extend(tabelas_por_equipa.get(str(c), []))
        return saida

    monkeypatch.setattr(AIService, "_get_user_crew_ids", _equipas)
    monkeypatch.setattr(AIService, "_is_space_member", _membro)
    monkeypatch.setattr(PermissionService, "get_authorized_tables", _tabelas)


EQUIPA_RH = str(uuid.uuid4())
EQUIPA_VENDAS = str(uuid.uuid4())
PROJETO = str(uuid.uuid4())


@pytest.mark.asyncio
async def test_outra_equipa_leva_403_e_a_fonte_nem_e_tocada(
    db_session, sem_redis, motor, monkeypatch
):
    """A pergunta foi feita na equipa de RH (salários). Quem abre é de Vendas:
    as tabelas dele não incluem `salarios` → 403, sem chamar o sky-ai."""
    from src.core.exceptions import ForbiddenError

    _permissoes(monkeypatch, [EQUIPA_VENDAS], {EQUIPA_RH: ["salarios"], EQUIPA_VENDAS: []})
    consulta = dav.ConsultaGuardada(
        sql="SELECT x FROM salarios LIMIT 5",
        connection_id=LIG,
        space_id=PROJETO,
        crew_id=EQUIPA_RH,
    )
    with pytest.raises(ForbiddenError):
        await dav.reexecutar(db_session, _Pessoa(), consulta)
    assert motor == []


@pytest.mark.asyncio
async def test_quem_esta_na_equipa_recebe_so_as_tabelas_dela(
    db_session, sem_redis, motor, monkeypatch
):
    _permissoes(
        monkeypatch,
        [EQUIPA_RH, EQUIPA_VENDAS],
        {EQUIPA_RH: ["salarios"], EQUIPA_VENDAS: ["encomendas"]},
    )
    consulta = dav.ConsultaGuardada(
        sql="SELECT x FROM salarios LIMIT 5",
        connection_id=LIG,
        space_id=PROJETO,
        crew_id=EQUIPA_RH,
        total_na_resposta=4,
    )
    r = await dav.reexecutar(db_session, _Pessoa(), consulta)
    assert r["ao_vivo"] and r["linhas"] == [["Norte", 10]]
    assert r["nota"] == dav.NOTA_AO_VIVO
    assert r["mudou_desde_a_resposta"] is True  # 4 na resposta, 1 agora
    # Só a equipa da pergunta — não as outras equipas da pessoa.
    assert motor[0]["tabelas_autorizadas"] == {LIG: ["salarios"]}


@pytest.mark.asyncio
async def test_nao_reexecutavel_diz_porque_sem_inventar_linhas(db_session, sem_redis, monkeypatch):
    from src.services.dados_ao_vivo import ReexecucaoRecusada

    _permissoes(monkeypatch, [EQUIPA_RH], {EQUIPA_RH: ["t"]})

    async def _recusa(self, connection_id, **kw):
        raise ReexecucaoRecusada(422, "nao_reexecutavel")

    async def _seg(**kw):
        return None

    monkeypatch.setattr("src.ai.http_client.AIServiceHTTPClient.reexecutar_sql", _recusa)
    monkeypatch.setattr("src.services.security_config_builder.build_security_config", _seg)
    r = await dav.reexecutar(
        db_session,
        _Pessoa(),
        dav.ConsultaGuardada(sql="SELECT a FROM dataset_1", connection_id=LIG, space_id=PROJETO),
    )
    assert r["reexecutavel"] is False and r["motivo"] == "nao_reexecutavel" and r["linhas"] == []


# ── 3. A cache é curta e de cada um ──────────────────────────────────


@pytest.mark.asyncio
async def test_cache_por_pessoa_e_com_prazo(db_session, sem_redis, motor, monkeypatch):
    _permissoes(monkeypatch, [EQUIPA_RH], {EQUIPA_RH: ["t"]})
    consulta = dav.ConsultaGuardada(sql="SELECT a FROM t", connection_id=LIG, space_id=PROJETO)
    ana, rui = _Pessoa(), _Pessoa()

    a1 = await dav.reexecutar(db_session, ana, consulta)
    a2 = await dav.reexecutar(db_session, ana, consulta)
    assert (a1["em_cache"], a2["em_cache"]) == (False, True)
    assert len(motor) == 1

    # Outra pessoa não herda a cache de ninguém: as tabelas dela podem ser outras.
    await dav.reexecutar(db_session, rui, consulta)
    assert len(motor) == 2

    # Passado o prazo, volta à fonte.
    real = time.monotonic
    monkeypatch.setattr(dav.time, "monotonic", lambda: real() + dav._ttl() + 1)
    a3 = await dav.reexecutar(db_session, ana, consulta)
    assert a3["em_cache"] is False and len(motor) == 3


def test_o_prazo_nunca_passa_de_5_minutos(monkeypatch):
    from src.config.settings import settings

    monkeypatch.setattr(settings, "DADOS_AO_VIVO_TTL_SECONDS", 3600)
    assert dav._ttl() == 300


# ── Widgets pelo HTTP ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o_widget_volta_a_correr_ao_abrir(
    async_client, test_user, valid_access_token, db_session, sem_redis, motor, monkeypatch
):
    async def _tabelas(db, uid, consulta):
        return {consulta.connection_id: ["t"]}

    monkeypatch.setattr(dav, "tabelas_de_quem_abre", _tabelas)
    user = test_user["user"]
    pid = uuid.uuid4()
    db_session.add(Page(id=pid, name="P", type="personal", color="#FAB721", owner_id=user.id))
    await db_session.flush()
    w = Widget(
        page_id=pid,
        type="chart",
        title="Vendas",
        position={"x": 0, "y": 0},
        size={"width": 1, "height": 1},
        data={"sql": "SELECT regiao, total FROM t", "data": LINHAS},
    )
    db_session.add(w)
    await db_session.commit()

    # Na base: a definição, sem as linhas.
    await db_session.refresh(w)
    assert not _tem_linhas(w.data) and w.data["sql"].startswith("SELECT")

    # Sem ligação não há onde voltar a correr: diz porquê, sem inventar.
    r = await async_client.get(f"/api/v1/widgets/{w.id}/data", headers=bearer(valid_access_token))
    assert r.status_code == 200, r.text
    assert r.json()["ao_vivo"] is False and r.json()["motivo"] == "sem_sql"

    # Com ligação: as linhas de AGORA, na forma de sempre.
    w.connection_id = uuid.UUID(LIG)
    await db_session.commit()
    r = await async_client.get(f"/api/v1/widgets/{w.id}/data", headers=bearer(valid_access_token))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ao_vivo"] is True and corpo["nota"] == dav.NOTA_AO_VIVO
    assert corpo["data"]["data"] == [{"regiao": "Norte", "total": 10}]
    assert motor[-1]["sql"] == "SELECT regiao, total FROM t"
    # E continua sem nada gravado.
    await db_session.refresh(w)
    assert not _tem_linhas(w.data)


@pytest.mark.asyncio
async def test_widget_de_pagina_alheia_e_404(
    async_client, valid_access_token, db_session, sem_redis, motor
):
    from src.models.user import User

    outro = User(
        id=uuid.uuid4(), email=f"o{uuid.uuid4().hex[:6]}@x.pt", name="O", password_hash="x"
    )
    db_session.add(outro)
    pid = uuid.uuid4()
    db_session.add(Page(id=pid, name="P", type="personal", color="#FAB721", owner_id=outro.id))
    await db_session.flush()
    w = Widget(
        page_id=pid,
        type="chart",
        title="x",
        position={"x": 0, "y": 0},
        size={"width": 1, "height": 1},
        data={"sql": "SELECT a FROM t"},
    )
    db_session.add(w)
    await db_session.commit()
    r = await async_client.get(f"/api/v1/widgets/{w.id}/data", headers=bearer(valid_access_token))
    assert r.status_code == 404
    assert motor == []


def test_hidratar_poe_as_linhas_onde_o_cliente_as_le():
    vivo = {"colunas": ["regiao", "total"], "linhas": [["Norte", 10]]}
    assert dav.hidratar_widget("chart", {"mapping": {}}, vivo)["data"] == [
        {"regiao": "Norte", "total": 10}
    ]
    t = dav.hidratar_widget("table", {}, vivo)
    assert t["columns"] == ["regiao", "total"] and t["rows"] == [{"regiao": "Norte", "total": 10}]
    k = dav.hidratar_widget("kpi", {}, {"colunas": ["total"], "linhas": [[17]]})
    assert k["value"] == 17
    a = dav.hidratar_widget(
        "insight", {"rows": {"columns": ["regiao"]}, "source": "agent_finding"}, vivo
    )
    assert a["rows"]["data"] == [["Norte", 10]]


def test_serie_do_achado():
    assert dav.serie_das_linhas(["mes", "v"], [["Jan", 1], ["Fev", 2.5]]) == [
        {"t": "Jan", "v": 1.0},
        {"t": "Fev", "v": 2.5},
    ]
    assert dav.serie_das_linhas(["a"], [["x"]]) == []


# ── Idempotência: estado e id, nunca o corpo ─────────────────────────


def test_idempotencia_guarda_so_o_id():
    from src.api.middleware.idempotency import id_do_recurso, resposta_de_repeticao

    corpo = json.dumps({"id": "w1", "data": {"data": LINHAS}}).encode()
    assert id_do_recurso(corpo) == "w1"
    r = resposta_de_repeticao({"status_code": 201, "resource_id": "w1"})
    assert r.status_code == 201
    assert json.loads(r.body) == {"idempotent_replay": True, "id": "w1"}
    assert not _tem_linhas(json.loads(r.body))


# ── 4. A limpeza: contar primeiro, aplicar é seguro ──────────────────


@pytest.mark.asyncio
async def test_limpeza_conta_sem_mexer_e_aplica_uma_vez(db_session, test_user):
    import importlib.util
    from pathlib import Path

    caminho = Path(__file__).resolve().parents[2] / "scripts" / "limpar_linhas_do_cliente.py"
    spec = importlib.util.spec_from_file_location("limpar_linhas_do_cliente", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    user = test_user["user"]
    pid = uuid.uuid4()
    db_session.add(Page(id=pid, name="P", type="personal", color="#FAB721", owner_id=user.id))
    await db_session.commit()

    # Linhas gravadas «à antiga», por SQL — como estão hoje em produção.
    conn = await db_session.connection()
    linhas = json.dumps(LINHAS)
    wid, demo, qid = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO widgets (id, page_id, type, title, position, size, data, z_index, source)"
            " VALUES (:id, :p, 'chart', 't', '{}', '{}', :d, 0, 'ai_synthesis')"
        ),
        {"id": wid, "p": pid.hex, "d": json.dumps({"sql": "SELECT 1", "data": LINHAS})},
    )
    await conn.execute(
        text(
            "INSERT INTO widgets (id, page_id, type, title, position, size, data, z_index, source)"
            " VALUES (:id, :p, 'chart', 'demo', '{}', '{}', :d, 0, 'demo_sectorial')"
        ),
        {"id": demo, "p": pid.hex, "d": json.dumps({"data": LINHAS})},
    )
    await conn.execute(
        text(
            "INSERT INTO ai_queries (id, user_id, page_id, question, status, configure_data,"
            " data_sample) VALUES (:id, :u, :p, 'q', 'completed', '{}', :d)"
        ),
        {"id": qid, "u": user.id.hex, "p": pid.hex, "d": linhas},
    )

    contado = await mod.limpar_uma_base(conn, aplicar=False)
    assert contado["widgets.data"] == 1  # o de demonstração não conta
    assert contado["ai_queries.data_sample"] == 1
    ainda = (
        await conn.execute(text("SELECT data_sample FROM ai_queries WHERE id = :i"), {"i": qid})
    ).scalar()
    assert _tem_linhas(ainda)  # contar não mexe

    aplicado = await mod.limpar_uma_base(conn, aplicar=True)
    assert aplicado == contado
    depois = (
        await conn.execute(text("SELECT data FROM widgets WHERE id = :i"), {"i": wid})
    ).scalar()
    assert not _tem_linhas(depois) and "SELECT 1" in depois
    d_demo = (
        await conn.execute(text("SELECT data FROM widgets WHERE id = :i"), {"i": demo})
    ).scalar()
    assert _tem_linhas(d_demo)

    segunda = await mod.limpar_uma_base(conn, aplicar=True)
    assert all(n == 0 for n in segunda.values())
