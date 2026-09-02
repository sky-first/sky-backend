"""O seed de utilizadores de um cliente: papel, conta apagada e base certa.

Este script passou a ser o que garante a conta com que o revisor das
lojas entra na app. Tres coisas tem de ser verdade, e nenhuma delas era
antes:

1. a conta pode nao ser administrador;
2. uma conta apagada em soft-delete volta ao servico;
3. com ``TENANT_SLUG``, escreve-se na base do CLIENTE — nunca na da
   plataforma. Este e o unico dos tres que falha em silencio: o script
   diria "criado" e a pessoa continuaria sem entrar.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _carregar():
    caminho = RAIZ / "scripts" / "seed_tenant_admin_user.py"
    spec = importlib.util.spec_from_file_location("seed_tenant_admin_user", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["seed_tenant_admin_user"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


class _Utilizador:
    def __init__(self, deleted_at=None, role="member"):
        self.email = "reviewer@sandbox.skyfirstlabs.com"
        self.password_hash = "antigo"
        self.role = role
        self.deleted_at = deleted_at
        self.email_verified = False
        self.has_completed_onboarding = False


class _Sessao:
    def __init__(self, linha):
        self._linha = linha
        self.adicionados = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, _):
        linha = self._linha

        class _R:
            def scalar_one_or_none(self):
                return linha

        return _R()

    def add(self, obj):
        self.adicionados.append(obj)

    async def commit(self):
        pass


def _montar(monkeypatch, linha, **ambiente):
    modulo = _carregar()
    monkeypatch.setattr(modulo, "get_password_hash", lambda p: f"hash:{p}")
    sessao = _Sessao(linha)
    monkeypatch.setattr(modulo, "create_async_engine", lambda *a, **k: _Motor())
    monkeypatch.setattr(modulo, "async_sessionmaker", lambda *a, **k: lambda: sessao)
    monkeypatch.setenv("TENANT_ADMIN_EMAIL", "reviewer@sandbox.skyfirstlabs.com")
    monkeypatch.setenv("TENANT_ADMIN_PASSWORD", "uma-password-longa-o-suficiente")
    for k, v in ambiente.items():
        monkeypatch.setenv(k, v)
    return modulo, sessao


class _Motor:
    async def dispose(self):
        pass


@pytest.mark.asyncio
async def test_papel_por_omissao_continua_super_admin(monkeypatch):
    """O onboarding depende disto — nao pode mudar por causa do revisor."""
    modulo, sessao = _montar(
        monkeypatch, None, DATABASE_URL="postgresql://x/y", TENANT_ADMIN_NAME="Admin"
    )
    monkeypatch.delenv("TENANT_ADMIN_ROLE", raising=False)
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    await modulo.main()

    assert sessao.adicionados[0].role == "super_admin"


@pytest.mark.asyncio
async def test_papel_pode_ser_member(monkeypatch):
    """O revisor tem de ver a app a trabalhar, nao de a administrar."""
    modulo, sessao = _montar(
        monkeypatch, None, DATABASE_URL="postgresql://x/y", TENANT_ADMIN_ROLE="member"
    )
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    await modulo.main()

    assert sessao.adicionados[0].role == "member"


@pytest.mark.asyncio
async def test_conta_apagada_volta_ao_servico(monkeypatch):
    apagada = _Utilizador(deleted_at="2026-08-20T10:00:00")
    modulo, _ = _montar(monkeypatch, apagada, DATABASE_URL="postgresql://x/y")
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    await modulo.main()

    assert apagada.deleted_at is None, "ficou apagada — a pessoa nao entra"
    assert apagada.password_hash.startswith("hash:")


@pytest.mark.asyncio
async def test_com_slug_escreve_na_base_do_cliente(monkeypatch):
    """O engano perigoso: semear na plataforma julgando ser o cliente."""
    modulo, _ = _montar(
        monkeypatch,
        None,
        DATABASE_URL="postgresql://plataforma/sky",
        TENANT_SLUG="sandbox",
    )

    usados = []
    monkeypatch.setattr(
        modulo, "create_async_engine", lambda url, **k: usados.append(url) or _Motor()
    )

    import types

    falso = types.ModuleType("_ligacao_ao_tenant")

    async def url_do_tenant(slug):
        assert slug == "sandbox"
        return "postgresql://cliente/tenant_sandbox"

    falso.url_do_tenant = url_do_tenant
    sys.modules["_ligacao_ao_tenant"] = falso

    await modulo.main()

    assert len(usados) == 1
    assert "tenant_sandbox" in usados[0], f"escreveu em {usados[0]}"
    assert "plataforma" not in usados[0], "escreveu na base da PLATAFORMA"


@pytest.mark.asyncio
async def test_sem_slug_usa_o_database_url(monkeypatch):
    modulo, _ = _montar(monkeypatch, None, DATABASE_URL="postgresql://directo/base")
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    usados = []
    monkeypatch.setattr(
        modulo, "create_async_engine", lambda url, **k: usados.append(url) or _Motor()
    )

    await modulo.main()

    assert "directo" in usados[0]


@pytest.mark.asyncio
async def test_papel_pedido_corrige_conta_que_ja_existe(monkeypatch):
    """A conta do revisor ficou super_admin por ter sido criada antes."""
    ja_existe = _Utilizador(role="super_admin")
    modulo, _ = _montar(
        monkeypatch,
        ja_existe,
        DATABASE_URL="postgresql://x/y",
        TENANT_ADMIN_ROLE="member",
    )
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    await modulo.main()

    assert ja_existe.role == "member"


@pytest.mark.asyncio
async def test_sem_papel_pedido_nao_promove_ninguem(monkeypatch):
    """Impor super_admin por omissao promovia quem foi despromovido de proposito."""
    despromovido = _Utilizador(role="member")
    modulo, _ = _montar(monkeypatch, despromovido, DATABASE_URL="postgresql://x/y")
    monkeypatch.delenv("TENANT_ADMIN_ROLE", raising=False)
    monkeypatch.delenv("TENANT_SLUG", raising=False)

    await modulo.main()

    assert despromovido.role == "member", "promoveu uma conta que ninguem mandou promover"
