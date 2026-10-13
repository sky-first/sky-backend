# -*- coding: utf-8 -*-
"""Consola — rotas das fontes do sistema (contrato em docs/contrato-fontes-do-sistema.md)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.api.v1 import console_fontes_sistema as rotas
from src.config.settings import settings
from src.main import app
from src.models.fonte_sistema import FonteSistema, FonteSistemaCliente
from src.models.internal_console import InternalConsoleAudit
from src.models.tenant import Tenant
from src.models.user import User

EMAIL = "lucas@skyfirstlabs.com"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "")
    monkeypatch.setattr(settings, "FONTES_SISTEMA_ENABLED", True)
    monkeypatch.setattr(settings, "WORLD_ADMIN_DSN", "")
    import src.api.middleware.rate_limit as _rl_mod

    async def _no_redis():
        return None

    monkeypatch.setattr(_rl_mod, "get_redis", _no_redis)
    enfileiradas: list = []

    class _R:
        id = "job-1"

    def _send(nome, args=None, **kw):
        enfileiradas.append((nome, args))
        return _R()

    import src.workers.celery_app as _celery_mod

    monkeypatch.setattr(_celery_mod.celery_app, "send_task", _send)
    yield enfileiradas


@pytest_asyncio.fixture
async def cliente_http(console_async_client):
    user = User(
        id=uuid.uuid4(),
        email=EMAIL,
        password_hash="",
        name="Lucas",
        role="admin",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_sky_team] = lambda: user
    yield console_async_client
    app.dependency_overrides.pop(require_sky_team, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def ceo(monkeypatch):
    monkeypatch.setenv("CONSOLE_ADMIN_EMAILS", EMAIL)


@pytest_asyncio.fixture
async def dados(db_session):
    t = Tenant(
        id=uuid.uuid4(),
        slug="sandbox",
        display_name="Sandbox",
        tier="starter",
        db_host="h",
        db_name="tenant_sandbox",
        db_credentials_secret_arn="arn",
        redis_host="r",
        redis_credentials_secret_arn="arn",
        sso_provider="none",
    )
    db_session.add(t)
    comum = dict(
        tipo="A",
        ferramentas=[],
        uso_comercial=True,
        cadencia_min=30,
        conta_como_fonte=False,
        versao=1,
    )
    db_session.add_all(
        [
            FonteSistema(
                id="combustivel_es",
                nome={"pt": "Combustível ES"},
                estado="ativa",
                tabelas=["gasolineras_precio"],
                nome_carregador=["gasolineras"],
                planos_permitidos=["starter", "core", "plus", "enterprise"],
                **comum,
            ),
            FonteSistema(
                id="trafego_dgt",
                nome={"pt": "Trânsito"},
                estado="rascunho",
                tabelas=["incidencias_trafico"],
                nome_carregador=["incidencias"],
                planos_permitidos=["starter", "core", "plus", "enterprise"],
                **comum,
            ),
            FonteSistema(
                id="so_plus",
                nome={"pt": "Só Plus"},
                estado="ativa",
                tabelas=["cambio_eur"],
                nome_carregador=["cambio"],
                planos_permitidos=["plus", "enterprise"],
                **comum,
            ),
        ]
    )
    await db_session.commit()
    return t


URL = "/api/console/v1/tenants/sandbox/fontes-sistema"


@pytest.mark.asyncio
async def test_com_a_flag_desligada_tudo_da_404(cliente_http, dados, monkeypatch):
    monkeypatch.setattr(settings, "FONTES_SISTEMA_ENABLED", False)
    for metodo, url, corpo in (
        ("GET", "/api/console/v1/fontes-sistema", None),
        ("GET", URL, None),
        ("PUT", URL + "/combustivel_es", {"ativa": True}),
        ("POST", URL + "/reconciliar", None),
    ):
        r = await cliente_http.request(metodo, url, json=corpo)
        assert r.status_code == 404, (url, r.text)
        assert r.json()["error"]["details"]["reason"] == "fontes_sistema_desligadas"


@pytest.mark.asyncio
async def test_catalogo_lista_fontes_e_diz_que_nao_ha_frescura(cliente_http, dados):
    r = await cliente_http.get("/api/console/v1/fontes-sistema")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["frescura_disponivel"] is False
    ids = {f["id"]: f for f in corpo["fontes"]}
    assert set(ids) == {"combustivel_es", "trafego_dgt", "so_plus"}
    assert ids["combustivel_es"]["conta_como_fonte"] is False
    assert ids["combustivel_es"]["clientes_ativos"] == 0
    assert ids["combustivel_es"]["frescura"] is None


@pytest.mark.asyncio
async def test_frescura_atrasada(cliente_http, dados, monkeypatch):
    velho = datetime.now(timezone.utc) - timedelta(hours=3)

    async def _mapa():
        return {
            "gasolineras": {
                "estado": "ok",
                "dado_de": velho,
                "ultima_actualizacao": velho,
                "linhas": 11000,
                "erro": None,
            }
        }

    monkeypatch.setattr(rotas, "_ler_frescura", _mapa)
    r = await cliente_http.get(URL + "/combustivel_es")
    f = r.json()["frescura"]
    assert f["estado"] == "ok" and f["linhas"] == 11000
    assert f["atrasada"] is True  # 3 h > 2 × 30 min


@pytest.mark.asyncio
async def test_marcar_sem_permissao_da_403(cliente_http, dados):
    r = await cliente_http.put(URL + "/combustivel_es", json={"ativa": True})
    assert r.status_code == 403, r.text
    d = r.json()["error"]["details"]
    assert d["reason"] == "permission_denied"
    assert d["required_action"] == "system_sources.toggle"


@pytest.mark.asyncio
async def test_marcar_aceita_enfileira_e_audita(cliente_http, dados, ceo, db_session, _ambiente):
    r = await cliente_http.put(URL + "/combustivel_es", json={"ativa": True})
    assert r.status_code == 202, r.text
    assert r.json() == {
        "fonte_id": "combustivel_es",
        "ativa": True,
        "estado": "a_preparar",
        "job_id": "job-1",
    }
    assert _ambiente == [(rotas.TAREFA_CONVERGIR, ["sandbox"])]
    row = (
        await db_session.execute(
            select(FonteSistemaCliente).where(FonteSistemaCliente.tenant_id == dados.id)
        )
    ).scalar_one()
    assert row.ativa and row.estado == "a_preparar" and row.ativada_por == EMAIL
    pedido_1 = row.pedido_id
    audit = (await db_session.execute(select(InternalConsoleAudit))).scalars().all()
    assert [(a.action, a.result) for a in audit] == [("enable_system_source", "success")]

    # Idempotente: o mesmo pedido outra vez é aceite e muda o pedido_id.
    r = await cliente_http.put(URL + "/combustivel_es", json={"ativa": True})
    assert r.status_code == 202
    await db_session.refresh(row)
    assert row.pedido_id != pedido_1

    lista = (await cliente_http.get(URL)).json()
    estados = {f["fonte_id"]: f for f in lista["fontes"]}
    assert lista["plano"] == "starter"
    assert estados["combustivel_es"]["ativa"] is True
    assert estados["trafego_dgt"]["estado"] == "nunca_ativada"
    assert estados["trafego_dgt"]["ativavel"] is False
    assert estados["trafego_dgt"]["motivo_nao_ativavel"] == "fonte_nao_ativa"
    assert estados["so_plus"]["permitida_pelo_plano"] is False

    cat = (await cliente_http.get("/api/console/v1/fontes-sistema")).json()
    assert {f["id"]: f["clientes_ativos"] for f in cat["fontes"]}["combustivel_es"] == 1


@pytest.mark.asyncio
async def test_marcar_fonte_em_rascunho_da_409(cliente_http, dados, ceo, db_session):
    r = await cliente_http.put(URL + "/trafego_dgt", json={"ativa": True})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["details"]["reason"] == "fonte_nao_ativa"
    audit = (await db_session.execute(select(InternalConsoleAudit))).scalars().all()
    assert [(a.action, a.result) for a in audit] == [("enable_system_source", "failure")]


@pytest.mark.asyncio
async def test_marcar_fonte_que_o_plano_nao_permite_da_409(cliente_http, dados, ceo):
    r = await cliente_http.put(URL + "/so_plus", json={"ativa": True})
    assert r.status_code == 409
    d = r.json()["error"]["details"]
    assert d["reason"] == "plano_nao_permite" and d["plano"] == "starter"


@pytest.mark.asyncio
async def test_desmarcar_o_que_nunca_esteve_activo_nao_enfileira(
    cliente_http, dados, ceo, _ambiente
):
    r = await cliente_http.put(URL + "/combustivel_es", json={"ativa": False})
    assert r.status_code == 202
    assert r.json()["estado"] == "desligada" and r.json()["job_id"] is None
    assert _ambiente == []


@pytest.mark.asyncio
async def test_desmarcar_poe_a_desligar(cliente_http, dados, ceo, db_session):
    await cliente_http.put(URL + "/combustivel_es", json={"ativa": True})
    r = await cliente_http.put(URL + "/combustivel_es", json={"ativa": False})
    assert r.status_code == 202 and r.json()["estado"] == "a_desligar"
    item = (await cliente_http.get(URL + "/combustivel_es")).json()
    assert item["ativa"] is False and item["estado"] == "a_desligar"
    assert item["desativada_por"] == EMAIL


@pytest.mark.asyncio
async def test_desconhecidos_dao_404(cliente_http, dados, ceo):
    r = await cliente_http.get("/api/console/v1/tenants/nao-existe/fontes-sistema")
    assert r.status_code == 404
    assert r.json()["error"]["details"]["reason"] == "tenant_not_found"
    r = await cliente_http.put(URL + "/nao_existe", json={"ativa": True})
    assert r.status_code == 404
    assert r.json()["error"]["details"]["reason"] == "fonte_not_found"


@pytest.mark.asyncio
async def test_reconciliar_enfileira(cliente_http, dados, ceo, _ambiente, db_session):
    r = await cliente_http.post(URL + "/reconciliar")
    assert r.status_code == 202
    assert r.json() == {"slug": "sandbox", "job_id": "job-1"}
    assert _ambiente == [(rotas.TAREFA_CONVERGIR, ["sandbox"])]
    audit = (await db_session.execute(select(InternalConsoleAudit))).scalars().all()
    assert [a.action for a in audit] == ["reconcile_system_sources"]
