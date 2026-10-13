# -*- coding: utf-8 -*-
"""Fontes do sistema contra um Postgres A SÉRIO — a fronteira está na base.

S2 (sem GRANT não lê), S3 (descoberta filtrada), S4 (não escreve nem cria),
S6 (REVOKE corta já), S18 (tectos do papel). Corre o mesmo
``scripts/fontes_sistema/bootstrap_sky_world.py`` que o Job do sky-infra.

Precisa de ``WORLD_TEST_PG_DSN`` (um superutilizador, ligado à base
``postgres``). Sem ela, salta — a CI define-a com o serviço ``postgres``.
Cria uma base e papéis com sufixo aleatório e apaga tudo no fim.
"""
from __future__ import annotations

import importlib.util
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio

DSN = os.environ.get("WORLD_TEST_PG_DSN")
if not DSN and os.environ.get("GITHUB_ACTIONS") == "true":
    # Na CI estes testes TÊM de correr: um salto silencioso aqui é a fronteira
    # comercial sem prova nenhuma, com a CI verde.
    raise RuntimeError("WORLD_TEST_PG_DSN em falta na CI (serviço postgres do ci-pr-gate)")
pytestmark = pytest.mark.skipif(not DSN, reason="sem WORLD_TEST_PG_DSN (Postgres real)")

RAIZ = Path(__file__).resolve().parents[2]


def _bootstrap_mod():
    caminho = RAIZ / "scripts" / "fontes_sistema" / "bootstrap_sky_world.py"
    spec = importlib.util.spec_from_file_location("bootstrap_sky_world", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dsn(base_dsn: str, *, user=None, password=None, base=None) -> str:
    p = urlsplit(base_dsn)
    host = p.hostname or "localhost"
    porta = p.port or 5432
    u = user or p.username
    pw = password if password is not None else (p.password or "")
    netloc = f"{u}:{pw}@{host}:{porta}"
    caminho = "/" + (base or p.path.lstrip("/") or "postgres")
    return urlunsplit((p.scheme.replace("+asyncpg", ""), netloc, caminho, p.query, ""))


@pytest.fixture(scope="module")
def mundo_real():
    import psycopg2

    sufixo = secrets.token_hex(3)
    base = f"sky_world_t{sufixo}"
    loader, admin = f"wl_{sufixo}", f"wa_{sufixo}"
    pw_loader, pw_admin = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    _bootstrap_mod().bootstrap(
        DSN, pw_loader, pw_admin, base=base, esquema="mundo", loader=loader, admin=admin
    )
    # Duas vezes: o Job corre a cada sync do ArgoCD.
    _bootstrap_mod().bootstrap(
        DSN, pw_loader, pw_admin, base=base, esquema="mundo", loader=loader, admin=admin
    )

    # O carregador cria as tabelas como dono.
    c = psycopg2.connect(_dsn(DSN, user=loader, password=pw_loader, base=base))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("CREATE TABLE mundo.fontes (nome text primary key, estado text)")
        cur.execute("CREATE TABLE mundo.gasolineras_precio (id int primary key, preco numeric)")
        cur.execute("CREATE TABLE mundo.cambio_eur (moeda text primary key, taxa numeric)")
        cur.execute("CREATE TABLE mundo.rotas_referencia (origem text primary key)")
        cur.execute("INSERT INTO mundo.fontes VALUES ('gasolineras', 'ok')")
        cur.execute("INSERT INTO mundo.gasolineras_precio VALUES (1, 1.459)")
        cur.execute("INSERT INTO mundo.cambio_eur VALUES ('USD', 1.08)")
        cur.execute("INSERT INTO mundo.rotas_referencia VALUES ('Madrid')")
    c.close()

    estado = dict(
        sufixo=sufixo,
        base=base,
        admin_dsn=_dsn(DSN, user=admin, password=pw_admin, base=base),
        slug=f"t{sufixo}",
        fonte=f"comb_{sufixo}",
        outra=f"camb_{sufixo}",
    )
    yield estado

    c = psycopg2.connect(DSN)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (base,)
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{base}"')
        cur.execute(
            "SELECT rolname FROM pg_roles WHERE rolname LIKE %s OR rolname LIKE %s "
            "OR rolname LIKE %s",
            (f"%{sufixo}", f"wt_t{sufixo}", f"wsrc_%{sufixo}"),
        )
        # Primeiro os papéis de cliente e de fonte (o admin é o «grantor»
        # das pertenças, e o PG16 não deixa largar um grantor com pertenças).
        ordem = {"wt_": 0, "wsrc_": 1}
        papeis = sorted(
            (r for (r,) in cur.fetchall()),
            key=lambda r: next((v for k, v in ordem.items() if r.startswith(k)), 2),
        )
        for r in papeis:
            try:
                cur.execute(f'DROP ROLE IF EXISTS "{r}"')
            except Exception:  # noqa: BLE001 — limpeza; não falha o teste
                pass
    c.close()


@pytest.fixture
def config(mundo_real, monkeypatch):
    from src.config.settings import settings
    from src.services.fontes_sistema import credenciais

    p = urlsplit(DSN)
    monkeypatch.setattr(settings, "WORLD_ADMIN_DSN", mundo_real["admin_dsn"])
    monkeypatch.setattr(settings, "WORLD_DB_HOST", p.hostname or "localhost")
    monkeypatch.setattr(settings, "WORLD_DB_PORT", p.port or 5432)
    monkeypatch.setattr(settings, "WORLD_DB_NAME", mundo_real["base"])
    monkeypatch.setattr(settings, "WORLD_SCHEMA", "mundo")
    monkeypatch.setattr(settings, "WORLD_SSL_MODE", "disable")
    monkeypatch.setattr(settings, "WORLD_CREDENTIAL_BACKEND", "local")
    monkeypatch.setattr(settings, "WORLD_TENANT_SECRET_PREFIX", "sky/test/world/tenants/")
    credenciais.esquecer_cache()
    return mundo_real


@pytest_asyncio.fixture
async def cliente_com_uma_fonte(config):
    from src.services.fontes_sistema.mundo import Mundo

    async with Mundo() as m:
        assert await m.garantir_papel_da_fonte(config["fonte"], ["gasolineras_precio"]) == []
        assert (
            await m.garantir_papel_da_fonte(config["outra"], ["cambio_eur", "rotas_referencia"])
            == []
        )
        await m.garantir_papel_do_cliente(config["slug"])
        await m.conceder(config["fonte"], config["slug"])
        # Segunda corrida: idempotente, e não roda a password.
        await m.garantir_papel_do_cliente(config["slug"])
        assert await m.fontes_do_cliente(config["slug"]) == {config["fonte"]}
    return config


async def _como_cliente(config):
    import asyncpg

    from src.config.settings import settings
    from src.services.fontes_sistema import credenciais

    u, pw = credenciais.ler(credenciais.ref_do_cliente(config["slug"]), sem_cache=True)
    return await asyncpg.connect(
        host=settings.WORLD_DB_HOST,
        port=settings.WORLD_DB_PORT,
        user=u,
        password=pw,
        database=settings.WORLD_DB_NAME,
    )


@pytest.mark.asyncio
async def test_world_role_sem_grant_recusa_select(cliente_com_uma_fonte):
    """S2 — o que o cliente não activou, o Postgres recusa."""
    import asyncpg

    c = await _como_cliente(cliente_com_uma_fonte)
    try:
        assert await c.fetchval("SELECT count(*) FROM mundo.gasolineras_precio") == 1
        assert await c.fetchval("SELECT count(*) FROM mundo.fontes") == 1
        for t in ("cambio_eur", "rotas_referencia"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await c.fetchval(f"SELECT count(*) FROM mundo.{t}")
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_world_role_insert_create_temp_recusados(cliente_com_uma_fonte):
    """S4 — só leitura, sem criar nada, nem desligando o read-only."""
    import asyncpg

    c = await _como_cliente(cliente_com_uma_fonte)
    try:
        assert await c.fetchval("SHOW default_transaction_read_only") == "on"
        for sql in (
            "INSERT INTO mundo.gasolineras_precio VALUES (2, 1)",
            "CREATE TABLE mundo.x (a int)",
            "CREATE TABLE public.x (a int)",
            "CREATE TEMP TABLE x (a int)",
        ):
            with pytest.raises(asyncpg.PostgresError):
                await c.execute(sql)
        await c.execute("SET default_transaction_read_only = off")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute("INSERT INTO mundo.gasolineras_precio VALUES (3, 1)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute("CREATE TABLE mundo.y (a int)")
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_world_role_statement_timeout(cliente_com_uma_fonte):
    """S18 — tectos do papel do cliente."""
    c = await _como_cliente(cliente_com_uma_fonte)
    try:
        assert await c.fetchval("SHOW statement_timeout") == "15s"
        assert await c.fetchval("SHOW idle_in_transaction_session_timeout") == "30s"
        assert await c.fetchval("SHOW work_mem") == "16MB"
        limite = await c.fetchval("SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user")
        assert limite == 5
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_metadata_sky_world_so_tabelas_com_privilegio_pg(cliente_com_uma_fonte):
    """S3 — a descoberta só vê as tabelas das fontes activas."""
    from src.connectors.sky_world import SkyWorldConnector
    from src.core.tenant_context import TenantContext, reset_current_tenant, set_current_tenant
    from src.services.fontes_sistema import credenciais

    cfg = cliente_com_uma_fonte
    token = set_current_tenant(
        TenantContext(slug=cfg["slug"], id=uuid.uuid4(), tier="starter", display_name="T")
    )
    try:
        meta = await SkyWorldConnector().get_metadata(
            {"credential_ref": credenciais.ref_do_cliente(cfg["slug"])}
        )
    finally:
        reset_current_tenant(token)
    assert {t["name"] for t in meta["tables"]} == {"gasolineras_precio", "fontes"}


@pytest.mark.asyncio
async def test_revoke_corta_o_acesso_na_consulta_seguinte(cliente_com_uma_fonte):
    """S6 — desmarcar é um REVOKE: a consulta seguinte já falha."""
    import asyncpg

    from src.services.fontes_sistema.mundo import Mundo

    cfg = cliente_com_uma_fonte
    c = await _como_cliente(cfg)
    try:
        assert await c.fetchval("SELECT count(*) FROM mundo.gasolineras_precio") == 1
        async with Mundo() as m:
            await m.revogar(cfg["fonte"], cfg["slug"])
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.fetchval("SELECT count(*) FROM mundo.gasolineras_precio")
    finally:
        await c.close()
        async with Mundo() as m:
            await m.conceder(cfg["fonte"], cfg["slug"])


@pytest.mark.asyncio
async def test_destroy_tenant_remove_papel_world_pg(config):
    """S20 — o papel do cliente desaparece do Postgres."""
    from src.services.fontes_sistema.mundo import Mundo

    slug = f"d{config['sufixo']}"
    async with Mundo() as m:
        await m.garantir_papel_da_fonte(config["fonte"], ["gasolineras_precio"])
        await m.garantir_papel_do_cliente(slug)
        await m.conceder(config["fonte"], slug)
        await m.remover_cliente(slug)
        assert not await m.papel_existe(f"wt_{slug}")
