"""A conta do revisor das lojas tem de sobreviver a ter sido apagada.

O `seed_review_account.py` corre num Job do ArgoCD a cada sync. Se ele
rebentar, o `sky-demo-seed` fica Degraded — mas o estrago a serio e outro:
o revisor da App Store abre a app, ve um ecra de login, e nao ha maneira
de entrar. E a causa n1 de rejeicao de apps atras de login.

Foi o que aconteceu: a conta tinha sido apagada em soft-delete, o seed
procurava-a com um filtro `deleted_at IS NULL`, nao a via, tentava criar
outra, e batia no indice unico de email.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _carregar_script():
    caminho = RAIZ / "scripts" / "seed_review_account.py"
    spec = importlib.util.spec_from_file_location("seed_review_account", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["seed_review_account"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


class _Utilizador:
    def __init__(self, deleted_at=None):
        self.email = "demo@skyfirstlabs.com"
        self.password_hash = "antigo"
        self.deleted_at = deleted_at


class _RepositorioFalso:
    """Espelha o repositorio real no que importa: o filtro do soft-delete."""

    def __init__(self, db, linha):
        self._linha = linha
        self.criou = False

    async def get_by_email(self, email):
        # Exactamente o que o repositorio real faz: `deleted_at IS NULL`.
        if self._linha is None or self._linha.deleted_at is not None:
            return None
        return self._linha

    async def get_by_email_including_deleted(self, email):
        return self._linha

    async def create(self, **kwargs):
        self.criou = True
        if self._linha is not None:
            # O indice unico de email. Sem a correccao, e aqui que o Job morre.
            raise AssertionError(
                "tentou criar uma conta que ja existe na base — "
                "duplicate key value violates unique constraint"
            )
        self._linha = _Utilizador()
        return self._linha


class _SessaoFalsa:
    def __init__(self):
        self.adicionados = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, _):
        class _R:
            def first(self_inner):
                return None  # sem tenant: o seed avisa e segue

        return _R()

    async def commit(self):
        pass

    async def refresh(self, _):
        pass

    def add(self, obj):
        self.adicionados.append(obj)


@pytest.fixture
def seed(monkeypatch):
    monkeypatch.setenv("REVIEW_ACCOUNT_PASSWORD", "uma-password-suficientemente-longa")
    modulo = _carregar_script()
    monkeypatch.setattr(modulo, "get_password_hash", lambda p: f"hash:{p}")
    return modulo


async def _correr(modulo, monkeypatch, linha):
    sessao = _SessaoFalsa()
    repos = {}

    def _fabrica(db):
        repos["r"] = _RepositorioFalso(db, linha)
        return repos["r"]

    monkeypatch.setattr(modulo, "AsyncSessionLocal", lambda: sessao)
    monkeypatch.setattr(modulo, "UserRepository", _fabrica)
    await modulo.seed()
    return repos["r"]


@pytest.mark.asyncio
async def test_conta_apagada_e_reposta_em_vez_de_recriada(seed, monkeypatch):
    apagada = _Utilizador(deleted_at="2026-08-20T10:00:00")

    repo = await _correr(seed, monkeypatch, apagada)

    assert not repo.criou, "criou uma segunda conta em vez de repor a que existe"
    assert apagada.deleted_at is None, "a conta ficou apagada — o revisor nao entra"
    assert apagada.password_hash.startswith("hash:")


@pytest.mark.asyncio
async def test_conta_viva_so_leva_password_nova(seed, monkeypatch):
    viva = _Utilizador()

    repo = await _correr(seed, monkeypatch, viva)

    assert not repo.criou
    assert viva.deleted_at is None
    assert viva.password_hash == "hash:uma-password-suficientemente-longa"


@pytest.mark.asyncio
async def test_sem_conta_nenhuma_e_criada(seed, monkeypatch):
    repo = await _correr(seed, monkeypatch, None)

    assert repo.criou, "base vazia e o seed nao criou a conta do revisor"
