"""As migrações passam a chegar às bases dos clientes, não só à da plataforma.

Encontrado a 18/08/2026 ao repovoar os dados do `skyfirstlabs`:

    column data_connections.nao_cruzavel does not exist

A plataforma estava em ``cross_project_20260818`` e as bases dos clientes duas e
três revisões atrás. O Job de migração só corria contra a base da plataforma, e
as dos clientes ficavam para trás **a cada deploy que trouxesse uma migração** —
até alguma coisa rebentar. Já tinha acontecido antes, com o chat a devolver 500
por falta de ``conversations.session_id``; nessa altura escreveu-se um runbook
manual em vez de automatizar.

Estes testes guardam as duas decisões que fazem o script valer a pena. Não
executam alembic nenhum: exercitam a escolha de quem migrar e a política de
falha, que é onde os erros deste tipo de script vivem.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _carregar():
    """O script vive em `scripts/`, fora do pacote — carrega-se pelo caminho."""
    caminho = Path(__file__).resolve().parents[2] / "scripts" / "migrate_tenants.py"
    spec = importlib.util.spec_from_file_location("migrate_tenants", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["migrate_tenants"] = modulo
    spec.loader.exec_module(modulo)  # type: ignore[union-attr]
    return modulo


def _cliente(slug, db_name, host="db.exemplo"):
    return SimpleNamespace(
        slug=slug,
        db_host=host,
        db_name=db_name,
        db_port=5432,
        db_credentials_secret_arn="arn:x",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_a_base_da_plataforma_nao_e_migrada_outra_vez(monkeypatch):
    """O `sky` aponta para a própria base da plataforma.

    É a semente reservada do registo, não um cliente. Sem esta guarda o script
    corria o alembic uma segunda vez contra a mesma base — inofensivo hoje, mas
    é o género de coisa que confunde quem lê os logs à procura de um problema a
    sério.
    """
    m = _carregar()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/skyaisaas")
    monkeypatch.setattr(m, "_url", lambda row: f"url://{row.db_name}")

    linhas = [
        _cliente("sky", "skyaisaas"),
        _cliente("skyfirstlabs", "tenant_skyfirstlabs"),
        _cliente("sandbox", "tenant_sandbox"),
    ]

    class _Res:
        def scalars(self_inner):
            return SimpleNamespace(all=lambda: linhas)

    class _Db:
        async def execute(self_inner, *_a, **_k):
            return _Res()

        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *_a):
            return False

    monkeypatch.setattr(m, "AsyncSessionLocal", lambda: _Db(), raising=False)
    import src.config.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Db())

    clientes = await m._clientes(None)

    assert [s for s, _ in clientes] == ["skyfirstlabs", "sandbox"]


@pytest.mark.asyncio
async def test_um_cliente_sem_base_dedicada_e_ignorado(monkeypatch):
    m = _carregar()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/skyaisaas")
    monkeypatch.setattr(m, "_url", lambda row: f"url://{row.db_name}")

    linhas = [_cliente("sem_base", None), _cliente("bom", "tenant_bom")]

    class _Res:
        def scalars(self_inner):
            return SimpleNamespace(all=lambda: linhas)

    class _Db:
        async def execute(self_inner, *_a, **_k):
            return _Res()

        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *_a):
            return False

    import src.config.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Db())

    clientes = await m._clientes(None)
    assert [s for s, _ in clientes] == ["bom"]


def test_falhar_num_cliente_trava_o_deploy(monkeypatch, capsys):
    """A política de falha, que é a decisão que importa.

    Um cliente esquecido é pior do que um deploy adiado: o deploy adiado vê-se,
    o cliente esquecido só se vê quando alguém se queixa. Se isto passar a
    devolver 0 com falhas, voltamos ao mundo em que uma base fica para trás em
    silêncio.
    """
    m = _carregar()
    monkeypatch.setattr(m, "_clientes", lambda slug: None)  # substituído a seguir pelo asyncio.run

    async def _falso(_slug):
        return [("a", "url://a"), ("b", "url://b")]

    monkeypatch.setattr(m, "_clientes", _falso)
    monkeypatch.setattr(m, "_migrar", lambda slug, url: slug != "b")
    monkeypatch.setattr(sys, "argv", ["migrate_tenants.py"])

    assert m.main() == 1
    saida = capsys.readouterr()
    assert "b" in saida.err


def test_correr_bem_devolve_zero(monkeypatch):
    m = _carregar()

    async def _falso(_slug):
        return [("a", "url://a")]

    monkeypatch.setattr(m, "_clientes", _falso)
    monkeypatch.setattr(m, "_migrar", lambda slug, url: True)
    monkeypatch.setattr(sys, "argv", ["migrate_tenants.py"])

    assert m.main() == 0


def test_o_url_com_credenciais_nunca_vai_para_o_ecra(monkeypatch, capsys):
    """O URL do cliente traz utilizador e password.

    O que se mostra é o slug e o erro do alembic — nunca o ambiente nem o URL.
    """
    m = _carregar()

    async def _falso(_slug):
        return [("a", "postgresql+asyncpg://utilizador:segredo@h:5432/tenant_a")]

    monkeypatch.setattr(m, "_clientes", _falso)
    monkeypatch.setattr(m, "_migrar", lambda slug, url: True)
    monkeypatch.setattr(sys, "argv", ["migrate_tenants.py"])

    m.main()
    saida = capsys.readouterr()
    assert "segredo" not in saida.out
    assert "segredo" not in saida.err


def test_corre_como_o_hook_o_corre():
    """O modo em que ele corre de verdade: `python scripts/migrate_tenants.py`.

    Os testes acima carregam o módulo pelo caminho, a partir do pytest, onde o
    `src` já é importável. Isso escondeu o defeito que apareceu **em produção**
    ao primeiro arranque: corrido como script, o Python põe `scripts/` no
    caminho e não a raiz, e o `from src.config.database import ...` rebenta com
    `ModuleNotFoundError: No module named 'src'`.

    E como o script falha alto de propósito, isso travou o deploy — a política
    certa a apanhar o erro errado.

    Não se testa a migração em si: aponta-se a uma base que não existe e
    verifica-se que a queixa é de ligação, nunca de importação.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    ambiente = dict(
        os.environ,
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/nao_existe",
    )
    r = subprocess.run(
        [sys.executable, "scripts/migrate_tenants.py", "--dry-run"],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=120,
    )

    tudo = r.stdout + r.stderr
    assert "ModuleNotFoundError" not in tudo, tudo[-2000:]
    assert "No module named 'src'" not in tudo
