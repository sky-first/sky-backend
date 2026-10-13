# -*- coding: utf-8 -*-
"""Fontes do sistema — os cenários de stress do desenho que se testam sem Postgres.

Cada teste tem o nome do cenário (S1…S20) de
``design-fontes-do-sistema.md`` §7. Os que precisam de papéis Postgres a
sério (S2, S4, S18) estão em ``test_fontes_sistema_postgres.py``.

A base ``sky_world`` é substituída por ``MundoFalso`` (memória), que guarda
papéis, membros e tabelas como o Postgres guardaria. A base da plataforma e
a do cliente são a mesma SQLite de teste — as tabelas não se cruzam.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Set

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config.settings import settings
from src.core.exceptions import ForbiddenError, LigacaoDoSistemaError, UnauthorizedError
from src.core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)
from src.models.connection import DataConnection
from src.models.fonte_sistema import FonteSistema, FonteSistemaCliente
from src.models.space import Space, SpaceConnection, SpaceTable
from src.models.tenant import Tenant
from src.models.user import User
from src.services.fontes_sistema import catalogo, credenciais, ligacao_gerida
from src.services.fontes_sistema import provisionamento as prov
from src.tests.conftest import TestSessionLocal

SLUG = "mopa"
CLIENTE = uuid.uuid4()


# ── Duplos ──────────────────────────────────────────────────────────────


class MundoFalso:
    """``sky_world`` em memória, com as mesmas regras que o Postgres impõe."""

    def __init__(self, tabelas: Set[str]):
        self.tabelas = set(tabelas) | {"fontes"}
        self.papeis: Set[str] = set()
        self.grants: Dict[str, Set[str]] = {}  # wsrc_x -> tabelas
        self.membros: Dict[str, Set[str]] = {}  # wt_slug -> {fonte_id}
        self.ao_conceder = None
        self.removidos: List[str] = []

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def papel_existe(self, nome):
        return nome in self.papeis

    async def garantir_papel_da_fonte(self, fonte_id, tabelas):
        papel = catalogo.papel_da_fonte(fonte_id)
        self.papeis.add(papel)
        desejadas = {t for t in tabelas if t not in catalogo.TABELAS_PROIBIDAS} | {"fontes"}
        self.grants[papel] = desejadas & self.tabelas
        return sorted(t for t in desejadas if t not in self.tabelas)

    async def garantir_papel_do_cliente(self, slug):
        self.papeis.add(catalogo.papel_do_cliente(slug))
        self.membros.setdefault(catalogo.papel_do_cliente(slug), set())

    async def fontes_do_cliente(self, slug):
        return set(self.membros.get(catalogo.papel_do_cliente(slug), set()))

    async def conceder(self, fonte_id, slug):
        self.membros.setdefault(catalogo.papel_do_cliente(slug), set()).add(fonte_id)
        if self.ao_conceder:
            await self.ao_conceder(fonte_id)

    async def revogar(self, fonte_id, slug):
        self.membros.get(catalogo.papel_do_cliente(slug), set()).discard(fonte_id)

    async def remover_cliente(self, slug):
        papel = catalogo.papel_do_cliente(slug)
        self.membros.pop(papel, None)
        self.papeis.discard(papel)
        self.removidos.append(slug)

    async def papeis_de_clientes(self):
        return {p for p in self.papeis if p.startswith("wt_")}

    def visiveis(self, slug) -> Set[str]:
        """O que ``has_table_privilege`` deixaria ver ao ``wt_<slug>``."""
        vis: Set[str] = set()
        for f in self.membros.get(catalogo.papel_do_cliente(slug), set()):
            vis |= self.grants.get(catalogo.papel_da_fonte(f), set())
        return vis


@asynccontextmanager
async def _contexto(slug):
    token = set_current_tenant(
        TenantContext(slug=slug, id=CLIENTE, tier="starter", display_name="Mopa")
    )
    try:
        yield True
    finally:
        reset_current_tenant(token)


@asynccontextmanager
async def _contexto_que_nao_resolve(slug):
    yield False


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def ligado(monkeypatch):
    monkeypatch.setattr(settings, "FONTES_SISTEMA_ENABLED", True)
    monkeypatch.setattr(settings, "WORLD_CREDENTIAL_BACKEND", "local")
    monkeypatch.setattr(settings, "WORLD_TENANT_SECRET_PREFIX", "sky/test/world/tenants/")
    credenciais.esquecer_cache()
    yield


def _fonte(id_, tabelas, **kw):
    base = dict(
        id=id_,
        nome={"pt": id_},
        tipo="A",
        estado="ativa",
        tabelas=tabelas,
        nome_carregador=[id_],
        ferramentas=[],
        uso_comercial=True,
        cadencia_min=30,
        planos_permitidos=["starter", "core", "plus", "enterprise"],
        conta_como_fonte=False,
        versao=1,
    )
    base.update(kw)
    return FonteSistema(**base)


@pytest_asyncio.fixture
async def mundo_cliente(db_session, ligado, monkeypatch):
    """Um cliente com dois projectos, o catálogo, e o sky_world falso."""
    db = db_session
    db.add(
        Tenant(
            id=CLIENTE,
            slug=SLUG,
            display_name="Mopa",
            tier="starter",
            db_host="h",
            db_name="tenant_mopa",
            db_credentials_secret_arn="arn",
            redis_host="r",
            redis_credentials_secret_arn="arn",
            sso_provider="none",
        )
    )
    admin = User(email="admin@mopa.pt", password_hash="x", name="Admin", role="admin")
    db.add(admin)
    await db.flush()
    s1 = Space(name="Operações", created_by=admin.id)
    s2 = Space(name="Privado", created_by=admin.id)
    db.add_all([s1, s2])
    db.add_all(
        [
            _fonte("combustivel_es", ["gasolineras_precio", "gasoleo_historico_diario"]),
            _fonte("cambio_bce", ["cambio_eur"]),
            _fonte("trafego_dgt", ["incidencias_trafico"], estado="rascunho"),
        ]
    )
    await db.commit()

    mundo = MundoFalso(
        {"gasolineras_precio", "gasoleo_historico_diario", "cambio_eur", "rotas_referencia"}
    )
    descobertas: list = []
    caches: list = []

    async def _sync(db_, lig):
        lig.status = "active"
        await db_.flush()
        return sorted(mundo.visiveis(SLUG))

    async def _descobrir(ligacao_id, spaces, slug, tabelas):
        descobertas.append((ligacao_id, sorted(str(s.id) for s in spaces), slug, list(tabelas)))
        return {}

    async def _cache(db_):
        caches.append(True)
        return 0

    monkeypatch.setattr(ligacao_gerida, "sincronizar_metadados", _sync)
    monkeypatch.setattr(ligacao_gerida, "descobrir", _descobrir)
    monkeypatch.setattr(ligacao_gerida, "invalidar_cache_semantica", _cache)

    class Mundo:
        pass

    Mundo.mundo, Mundo.descobertas, Mundo.caches = mundo, descobertas, caches
    Mundo.spaces, Mundo.admin = [s1, s2], admin
    yield Mundo


async def _pedir(fonte_id: str, ativa: bool):
    async with TestSessionLocal() as s:
        row = await s.get(FonteSistemaCliente, (CLIENTE, fonte_id))
        if row is None:
            row = FonteSistemaCliente(tenant_id=CLIENTE, fonte_id=fonte_id)
            s.add(row)
        row.ativa = ativa
        row.pedido_id = uuid.uuid4()
        row.estado = "a_preparar" if ativa else "a_desligar"
        await s.commit()


async def _convergir(m, **kw):
    return await prov.convergir_cliente(
        SLUG,
        mundo=m.mundo,
        sessao_plataforma=TestSessionLocal,
        sessao_do_cliente=TestSessionLocal,
        contexto=kw.pop("contexto", _contexto),
        **kw,
    )


async def _linha(fonte_id):
    async with TestSessionLocal() as s:
        return await s.get(FonteSistemaCliente, (CLIENTE, fonte_id))


async def _space_tables(conn_id):
    async with TestSessionLocal() as s:
        rows = (
            (await s.execute(select(SpaceTable).where(SpaceTable.connection_id == conn_id)))
            .scalars()
            .all()
        )
    return {(r.space_id, r.table_name) for r in rows}


async def _ligacao():
    async with TestSessionLocal() as s:
        return (
            await s.execute(select(DataConnection).where(DataConnection.sistema.is_(True)))
        ).scalar_one_or_none()


# ── Convergência: marcar e desmarcar ────────────────────────────────────


@pytest.mark.asyncio
async def test_marcar_converge_para_pronta_em_todos_os_projectos(mundo_cliente):
    m = mundo_cliente
    await _pedir("combustivel_es", True)
    r = await _convergir(m)

    assert r.get("erro") is None, r
    assert (await _linha("combustivel_es")).estado == "pronta"
    # GRANT feito no Postgres (falso).
    assert m.mundo.membros["wt_mopa"] == {"combustivel_es"}
    lig = await _ligacao()
    assert lig is not None and lig.connector_id == "sky-world" and lig.status == "active"
    # Sem password na config — só a referência.
    from src.utils.encryption import decrypt_dict

    cfg = decrypt_dict(lig.config)
    assert cfg["credential_ref"] == "sky/test/world/tenants/mopa"
    assert "password" not in cfg
    # Em TODOS os projectos, com as tabelas da fonte + fontes.
    esperadas = {"gasolineras_precio", "gasoleo_historico_diario", "fontes"}
    st = await _space_tables(lig.id)
    for s in m.spaces:
        assert {t for sid, t in st if sid == s.id} == esperadas
    async with TestSessionLocal() as s:
        ligados = set(
            (
                await s.execute(
                    select(SpaceConnection.space_id).where(SpaceConnection.connection_id == lig.id)
                )
            )
            .scalars()
            .all()
        )
    assert ligados == {sp.id for sp in m.spaces}


@pytest.mark.asyncio
async def test_provisionar_envia_x_tenant_slug_explicito(mundo_cliente):
    """S1 — o discover leva o slug por argumento, não pelo contextvar."""
    m = mundo_cliente
    await _pedir("combustivel_es", True)
    # O contextvar está na PLATAFORMA enquanto a tarefa corre.
    token = set_current_tenant(DEFAULT_TENANT_CONTEXT)
    try:
        await _convergir(m)
    finally:
        reset_current_tenant(token)
    assert m.descobertas, "o discover não foi chamado"
    _, spaces, slug, tabelas = m.descobertas[-1]
    assert slug == SLUG
    assert len(spaces) == 2
    assert "gasolineras_precio" in tabelas


@pytest.mark.asyncio
async def test_discover_http_usa_o_slug_dado_e_nao_o_contextvar(monkeypatch):
    """S1 — no próprio cliente HTTP: cabeçalho = argumento, mesmo na plataforma."""
    import httpx

    from src.ai.http_client import AIServiceHTTPClient

    vistos = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class _Cliente:
        def __init__(self, *a, headers=None, **kw):
            vistos["headers"] = dict(headers or {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, params=None):
            vistos["params"] = params
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Cliente)
    token = set_current_tenant(DEFAULT_TENANT_CONTEXT)
    try:
        await AIServiceHTTPClient("http://ai").discover_connection(
            connection_id="c", space_id=str(uuid.uuid4()), tenant_slug="sandbox"
        )
    finally:
        reset_current_tenant(token)
    assert vistos["headers"] == {"X-Tenant-Slug": "sandbox"}


@pytest.mark.asyncio
async def test_provisionar_falha_alto_sem_cliente_resolvido(mundo_cliente):
    """S1 — sem cliente resolvido, nada corre contra a base da plataforma."""
    m = mundo_cliente
    await _pedir("combustivel_es", True)
    r = await _convergir(m, contexto=_contexto_que_nao_resolve)
    linha = await _linha("combustivel_es")
    assert linha.estado == "erro"
    assert linha.erro["passo"] == "base_do_cliente"
    assert "ClienteNaoResolvido" in r["erro"]["mensagem"]
    assert await _ligacao() is None
    assert not m.descobertas


@pytest.mark.asyncio
async def test_desligar_revoga_tira_tabelas_e_invalida_cache_semantica(mundo_cliente):
    """S7 — desligar: REVOKE, space_tables fora, cache do cliente apagada."""
    m = mundo_cliente
    await _pedir("combustivel_es", True)
    await _pedir("cambio_bce", True)
    await _convergir(m)
    lig = await _ligacao()
    assert {t for _, t in await _space_tables(lig.id)} >= {"cambio_eur", "gasolineras_precio"}

    await _pedir("combustivel_es", False)
    m.caches.clear()
    await _convergir(m)

    assert m.mundo.membros["wt_mopa"] == {"cambio_bce"}
    tabelas = {t for _, t in await _space_tables(lig.id)}
    assert tabelas == {"cambio_eur", "fontes"}
    assert m.caches, "a cache semântica não foi invalidada"
    assert (await _linha("combustivel_es")).estado == "desligada"
    assert (await _linha("cambio_bce")).estado == "pronta"


@pytest.mark.asyncio
async def test_desligar_a_ultima_fonte_deixa_a_ligacao_inactiva_e_sem_tabelas(mundo_cliente):
    m = mundo_cliente
    await _pedir("cambio_bce", True)
    await _convergir(m)
    await _pedir("cambio_bce", False)
    await _convergir(m)
    lig = await _ligacao()
    assert lig is not None, "a ligação não se apaga (histórico, referências)"
    assert lig.status == "inactive"
    assert await _space_tables(lig.id) == set()
    assert m.mundo.membros["wt_mopa"] == set()


@pytest.mark.asyncio
async def test_toggle_concorrente_converge(mundo_cliente):
    """S17 — outro operador desmarca a meio da tarefa: o fim é coerente."""
    m = mundo_cliente
    await _pedir("combustivel_es", True)

    async def _outro_operador_desmarca(fonte_id):
        m.mundo.ao_conceder = None
        await _pedir("combustivel_es", False)

    m.mundo.ao_conceder = _outro_operador_desmarca
    r = await _convergir(m)

    assert r["voltas"] == 2
    assert m.mundo.membros["wt_mopa"] == set(), "GRANT ficou feito com a linha desmarcada"
    assert (await _linha("combustivel_es")).estado == "desligada"


@pytest.mark.asyncio
async def test_fonte_em_rascunho_marcada_a_mao_fica_em_erro_e_sem_grant(mundo_cliente):
    m = mundo_cliente
    await _pedir("trafego_dgt", True)
    await _convergir(m)
    linha = await _linha("trafego_dgt")
    assert linha.estado == "erro" and linha.erro["passo"] == "catalogo"
    assert "trafego_dgt" not in m.mundo.membros.get("wt_mopa", set())


@pytest.mark.asyncio
async def test_tabela_em_falta_no_sky_world_da_erro_visivel(mundo_cliente):
    m = mundo_cliente
    m.mundo.tabelas.discard("cambio_eur")
    await _pedir("cambio_bce", True)
    await _convergir(m)
    linha = await _linha("cambio_bce")
    assert linha.estado == "erro"
    assert "cambio_eur" in linha.erro["mensagem"]


@pytest.mark.asyncio
async def test_convergir_com_a_flag_desligada_nao_faz_nada(mundo_cliente, monkeypatch):
    m = mundo_cliente
    monkeypatch.setattr(settings, "FONTES_SISTEMA_ENABLED", False)
    await _pedir("combustivel_es", True)
    r = await _convergir(m)
    assert r["estado"] == "funcionalidade_desligada"
    assert m.mundo.membros == {}


# ── S8 — licença ────────────────────────────────────────────────────────


def test_catalogo_recusa_ativar_sem_uso_comercial():
    with pytest.raises(catalogo.FonteInvalidaError) as e:
        catalogo.validar_para_ativar(_fonte("x", ["cambio_eur"], uso_comercial=False))
    assert e.value.motivo == "sem_uso_comercial"


@pytest.mark.asyncio
async def test_base_recusa_fonte_activa_sem_uso_comercial(db_session):
    db_session.add(_fonte("nao_comercial", ["cambio_eur"], uso_comercial=False))
    with pytest.raises(IntegrityError):
        await db_session.commit()


def test_rotas_referencia_nunca_granted():
    for proibida in ("rotas_referencia", "gasolineras_rota"):
        with pytest.raises(catalogo.FonteInvalidaError) as e:
            catalogo.tabelas_da_fonte(_fonte("x", ["cambio_eur", proibida]))
        assert e.value.motivo == "tabela_proibida"


@pytest.mark.asyncio
async def test_mundo_nunca_concede_tabela_proibida_mesmo_pedida():
    """S8 — a última barreira está no código que faz o GRANT."""
    from src.services.fontes_sistema.mundo import Mundo

    feitos: list = []

    class _Conn:
        async def fetchval(self, sql, *a):
            return 1  # o papel existe

        async def fetch(self, sql, *a):
            if "pg_class" in sql:
                return [{"relname": t} for t in ("rotas_referencia", "cambio_eur", "fontes")]
            if "role_table_grants" in sql:
                return [{"table_name": "rotas_referencia"}, {"table_name": "cambio_eur"}]
            return []

        async def execute(self, sql, *a):
            feitos.append(sql)

    m = Mundo(dsn="x")
    m._conn = _Conn()
    await m.garantir_papel_da_fonte("cambio_bce", ["cambio_eur", "rotas_referencia"])
    grants = [s for s in feitos if s.startswith("GRANT SELECT")]
    assert any('"cambio_eur"' in s for s in grants)
    assert not any("rotas_referencia" in s for s in grants)
    # E uma concessão antiga dela é retirada.
    assert any(s.startswith("REVOKE") and "rotas_referencia" in s for s in feitos)


def test_identificadores_recusam_injeccao():
    from src.services.fontes_sistema.mundo import _ident

    for mau in ('x"; DROP ROLE world_admin; --', "Maiusc", "", "a b"):
        with pytest.raises(ValueError):
            _ident(mau)
    with pytest.raises(catalogo.FonteInvalidaError):
        catalogo.papel_do_cliente("mopa'; drop")
    assert catalogo.papel_do_cliente("gbt-solutions") == "wt_gbt_solutions"


@pytest.mark.asyncio
async def test_papel_do_cliente_fica_so_leitura_e_limitado():
    """S4/S18 (lado do código): o papel nasce com só-leitura e tectos."""
    from src.services.fontes_sistema import mundo as M

    feitos: list = []

    class _Conn:
        async def fetchval(self, sql, *a):
            return None  # não existe

        async def execute(self, sql, *a):
            feitos.append(sql)

    m = M.Mundo(dsn="x")
    m._conn = _Conn()
    orig = credenciais.guardar
    credenciais.guardar = lambda *a, **k: None
    old = (settings.WORLD_CREDENTIAL_BACKEND, settings.WORLD_TENANT_SECRET_PREFIX)
    settings.WORLD_CREDENTIAL_BACKEND = "local"
    settings.WORLD_TENANT_SECRET_PREFIX = "sky/test/world/tenants/"
    try:
        await m.garantir_papel_do_cliente("mopa")
    finally:
        credenciais.guardar = orig
        settings.WORLD_CREDENTIAL_BACKEND, settings.WORLD_TENANT_SECRET_PREFIX = old
    texto = "\n".join(feitos)
    assert 'CREATE ROLE "wt_mopa" WITH LOGIN' in texto and "CONNECTION LIMIT 5" in texto
    assert "SET default_transaction_read_only = 'on'" in texto
    assert "SET statement_timeout = '15s'" in texto
    assert "SET idle_in_transaction_session_timeout = '30s'" in texto
    assert "CREATEDB" not in texto.replace("NOCREATEDB", "")
    assert 'GRANT CONNECT ON DATABASE "sky_world" TO "wt_mopa"' in texto


# ── S3 — descoberta filtrada por privilégio ─────────────────────────────


@pytest.mark.asyncio
async def test_metadata_sky_world_so_tabelas_com_privilegio(monkeypatch, ligado):
    import asyncpg

    from src.connectors.sky_world import SkyWorldConnector

    ligacoes: list = []
    consultas: list = []

    class _Conn:
        async def fetch(self, sql, *a):
            consultas.append((sql, a))
            return []

        async def close(self):
            return None

    async def _connect(**kw):
        ligacoes.append(kw)
        return _Conn()

    monkeypatch.setattr(asyncpg, "connect", _connect)
    monkeypatch.setattr(settings, "WORLD_DB_HOST", "world.interno")
    monkeypatch.setattr(settings, "WORLD_DB_NAME", "sky_world")
    async with _contexto(SLUG):
        await SkyWorldConnector().get_metadata(
            {
                "credential_ref": "sky/test/world/tenants/mopa",
                # Um config adulterado não muda o destino nem o esquema.
                "host": "atacante.example.com",
                "database": "outra",
                "schema": "public",
            }
        )
    assert ligacoes[0]["host"] == "world.interno"
    assert ligacoes[0]["database"] == "sky_world"
    assert ligacoes[0]["user"] == "wt_mopa"
    sql, args = consultas[0]
    assert "has_table_privilege(c.oid, 'SELECT')" in sql
    assert "has_schema_privilege(n.oid, 'USAGE')" in sql
    assert args == ("mundo",)


# ── S15 — a ligação do sistema não se mexe ──────────────────────────────


def test_credential_ref_de_outro_cliente_recusada(ligado):
    with pytest.raises(credenciais.CredencialRecusadaError):
        credenciais.validar_ref("sky/test/world/tenants/outro", "mopa")
    with pytest.raises(credenciais.CredencialRecusadaError):
        credenciais.validar_ref("sky/test/world/tenants/mopa", None)  # plataforma
    assert credenciais.validar_ref("sky/test/world/tenants/mopa", "mopa").endswith("/mopa")


@pytest.mark.asyncio
async def test_conector_recusa_ref_de_outro_cliente_antes_do_segredo(ligado, monkeypatch):
    from src.connectors.sky_world import SkyWorldConnector

    lidas: list = []
    monkeypatch.setattr(credenciais, "ler", lambda ref, **k: lidas.append(ref) or ("u", "p"))
    async with _contexto(SLUG):
        with pytest.raises(credenciais.CredencialRecusadaError):
            SkyWorldConnector()._get_connection_params(
                {"credential_ref": "sky/test/world/tenants/gbtsolutions"}
            )
    assert lidas == [], "o segredo de outro cliente chegou a ser pedido"


async def _ligacao_do_sistema_de(db, dono_id) -> DataConnection:
    c = DataConnection(
        name="Dados públicos",
        connector_id="sky-world",
        config={},
        created_by=dono_id,
        sistema=True,
        status="active",
    )
    db.add(c)
    await db.commit()
    return c


@pytest.mark.asyncio
async def test_put_ligacao_sistema_403(db_session, test_user):
    from src.schemas.connection import ConnectionUpdate
    from src.services.connection_service import ConnectionService

    user = test_user["user"]
    c = await _ligacao_do_sistema_de(db_session, user.id)
    svc = ConnectionService(db_session)
    with pytest.raises(LigacaoDoSistemaError):
        await svc.update_connection(c.id, user, ConnectionUpdate(name="minha"))
    with pytest.raises(LigacaoDoSistemaError):
        await svc.delete_connection(c.id, user)
    with pytest.raises(LigacaoDoSistemaError):
        await svc.test_connection(c.id, user)
    with pytest.raises(LigacaoDoSistemaError):
        await svc.update_metadata(c.id, user, {"tables": []})


@pytest.mark.asyncio
async def test_put_ligacao_sistema_403_pela_api(async_client, db_session, test_user_with_tokens):
    user = test_user_with_tokens["user"]
    c = await _ligacao_do_sistema_de(db_session, user.id)
    r = await async_client.put(
        f"/api/v1/connections/{c.id}",
        json={"name": "re-apontada", "config": {"host": "atacante.example.com"}},
        headers={"Authorization": f"Bearer {test_user_with_tokens['access_token']}"},
    )
    assert r.status_code == 403, r.text
    corpo = r.json()["error"]
    assert corpo["code"] == "FORBIDDEN"
    assert corpo["details"]["reason"] == "ligacao_do_sistema"
    assert "pt" in corpo["details"]["messages"]


@pytest.mark.asyncio
async def test_permissoes_e_desligar_do_projecto_recusados(db_session, test_user):
    from src.schemas.permission import ConnectionPermissionCreate
    from src.services.permission_service import PermissionService
    from src.services.space_service import SpaceService

    user = test_user["user"]
    c = await _ligacao_do_sistema_de(db_session, user.id)
    sp = Space(name="Projecto", created_by=user.id)
    db_session.add(sp)
    await db_session.flush()
    db_session.add(SpaceConnection(space_id=sp.id, connection_id=c.id))
    await db_session.commit()

    campos = ConnectionPermissionCreate.model_fields
    dados = {"space_id": sp.id}
    if "access_level" in campos:
        dados["access_level"] = "full"
    with pytest.raises(LigacaoDoSistemaError):
        await PermissionService(db_session).create_connection_permission(
            c.id, user, ConnectionPermissionCreate(**dados)
        )
    svc = SpaceService(db_session)
    monkey_role = getattr(svc, "_require_space_role")

    async def _ok(*a, **k):
        return None

    svc._require_space_role = _ok
    try:
        with pytest.raises(LigacaoDoSistemaError):
            await svc.remove_space_connection(sp.id, c.id, user)
    finally:
        svc._require_space_role = monkey_role


# ── S14 — o plano não conta a ligação do sistema ────────────────────────


@pytest.mark.asyncio
async def test_contar_ligacoes_ignora_sistema(db_session, monkeypatch):
    from src.models.tenant_plan_limits import TenantPlanLimits
    from src.services import limites_do_plano as lim
    from src.services import planos

    monkeypatch.setattr(lim, "_sessao_da_plataforma", lambda: TestSessionLocal())
    token = set_current_tenant(
        TenantContext(slug=SLUG, id=CLIENTE, tier="starter", display_name="Mopa")
    )
    try:
        db_session.add(
            TenantPlanLimits(
                tenant_id=CLIENTE,
                tier="starter",
                **planos.tectos("starter"),
                queries_period_start=datetime.now(timezone.utc),
                last_threshold_alerted={},
            )
        )
        await db_session.commit()
        await _ligacao_do_sistema_de(db_session, uuid.uuid4())
        assert await lim._contar(db_session, "max_connections") == 0
        # O Starter continua a poder ligar a SUA base.
        await lim.verificar_criacao(db_session, "max_connections")
    finally:
        reset_current_tenant(token)


@pytest.mark.asyncio
async def test_criar_ligacao_ignora_campo_sistema_e_recusa_sky_world(db_session, test_user):
    from src.schemas.connection import ConnectionCreate
    from src.services.connection_service import ConnectionService

    user = test_user["user"]
    # O cliente não consegue pedir `sistema=true`: o esquema não o tem.
    pedido = ConnectionCreate(
        name="minha", connector_id="postgresql", config={"host": "h"}, sistema=True
    )
    assert "sistema" not in pedido.model_dump()
    # Nem criar uma ligação sky-world à mão (com a referência de outro cliente).
    with pytest.raises(LigacaoDoSistemaError):
        await ConnectionService(db_session).create_connection(
            user,
            ConnectionCreate(
                name="falsa",
                connector_id="sky-world",
                config={"credential_ref": "sky/production/world/tenants/outro"},
            ),
        )
    assert await _ligacao() is None


# ── S16 — o utilizador de sistema ───────────────────────────────────────


@pytest.mark.asyncio
async def test_apagar_admin_nao_apaga_ligacao_sistema(mundo_cliente, db_session):
    m = mundo_cliente
    await _pedir("cambio_bce", True)
    await _convergir(m)
    lig = await _ligacao()
    async with TestSessionLocal() as s:
        dono = await s.get(User, lig.created_by)
    assert dono.email == ligacao_gerida.EMAIL_SISTEMA
    assert dono.status == "sistema"
    assert lig.created_by != m.admin.id, "a ligação nasceu de um humano (CASCADE)"

    from src.services.user_service import UserService

    with pytest.raises(ForbiddenError):
        await UserService(db_session).delete_user(dono.id, m.admin)


@pytest.mark.asyncio
async def test_utilizador_de_sistema_nao_faz_login_nem_aparece_na_lista(db_session):
    from src.repositories.user import UserRepository
    from src.services.auth_service import AuthenticationService

    u = await ligacao_gerida.garantir_utilizador_de_sistema(db_session)
    await db_session.commit()
    with pytest.raises(UnauthorizedError):
        await AuthenticationService(db_session).login(email=u.email, password="qualquer")
    todos = await UserRepository(db_session).get_all()
    assert u.id not in {x.id for x in todos}


# ── S13 — projecto novo herda «Dados públicos» ──────────────────────────


@pytest.mark.asyncio
async def test_projeto_novo_herda_dados_publicos(mundo_cliente):
    m = mundo_cliente
    await _pedir("cambio_bce", True)
    await _convergir(m)
    lig = await _ligacao()

    async with TestSessionLocal() as s:
        novo = Space(name="Novo", created_by=m.admin.id)
        s.add(novo)
        await s.commit()
        assert await ligacao_gerida.ligar_projeto_novo(s, novo.id) is True
        await s.commit()
    tabelas = {t for sid, t in await _space_tables(lig.id) if sid == novo.id}
    assert tabelas == {"cambio_eur", "fontes"}

    # E a convergência seguinte inclui-o no discover.
    await _convergir(m)
    _, spaces, _, _ = m.descobertas[-1]
    assert str(novo.id) in spaces


@pytest.mark.asyncio
async def test_projeto_novo_sem_flag_nao_herda(mundo_cliente, monkeypatch):
    m = mundo_cliente
    await _pedir("cambio_bce", True)
    await _convergir(m)
    monkeypatch.setattr(settings, "FONTES_SISTEMA_ENABLED", False)
    async with TestSessionLocal() as s:
        novo = Space(name="Novo", created_by=m.admin.id)
        s.add(novo)
        await s.commit()
        assert await ligacao_gerida.ligar_projeto_novo(s, novo.id) is False


# ── S20 — destruir o cliente ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destroy_tenant_remove_papel_world(mundo_cliente, monkeypatch):
    m = mundo_cliente
    await _pedir("cambio_bce", True)
    await _convergir(m)
    apagados: list = []
    monkeypatch.setattr(credenciais, "apagar", lambda ref: apagados.append(ref))
    await prov.remover_cliente(SLUG, mundo=m.mundo, sessao_plataforma=TestSessionLocal)
    assert "wt_mopa" not in m.mundo.papeis
    assert apagados == ["sky/test/world/tenants/mopa"]
    assert await _linha("cambio_bce") is None


@pytest.mark.asyncio
async def test_reconciliacao_detecta_papel_orfao(mundo_cliente):
    m = mundo_cliente
    m.mundo.papeis |= {"wt_mopa", "wt_fantasma", "wsrc_cambio_bce"}
    orfaos = await prov.papeis_orfaos(mundo=m.mundo, sessao_plataforma=TestSessionLocal)
    assert orfaos == ["wt_fantasma"]


# ── Credenciais ─────────────────────────────────────────────────────────


def test_credencial_local_e_derivada_e_recusada_em_producao(ligado, monkeypatch):
    a = credenciais.ler("sky/test/world/tenants/mopa", sem_cache=True)
    b = credenciais.ler("sky/test/world/tenants/mopa", sem_cache=True)
    assert a == b and a[0] == "wt_mopa" and len(a[1]) >= 32
    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    with pytest.raises(credenciais.CredencialRecusadaError):
        credenciais.nova_password("mopa")
