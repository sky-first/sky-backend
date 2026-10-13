# -*- coding: utf-8 -*-
"""Credenciais de ligação nunca vão para a base em claro.

Quatro defeitos, encontrados numa auditoria (13/10/2026):

1. ``PATCH /connections/{id}`` com ``config`` gravava a config EM CLARO (era
   um TODO) e substituía-a inteira — um PATCH parcial apagava a password.
2. Sem ``ENCRYPTION_KEY``, o ``encrypt_dict`` devolvia o dicionário original
   em silêncio, em qualquer ambiente.
3. O filtro ``selected_tables`` lia a chave no blob cifrado → sempre None →
   nunca se aplicava.
4. Não havia forma de cifrar o que já estava em claro na base.

E o corpo de erro do sky-ai ia cru para os registos.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from src.config.settings import settings
from src.models.connection import ConnectionMetadata, DataConnection
from src.models.user import User
from src.schemas.connection import ConnectionUpdate
from src.services.connection_service import ConnectionService
from src.utils import encryption
from src.utils.encryption import (
    EncryptionKeyMissingError,
    decrypt_dict,
    encrypt_dict,
    is_encrypted,
)

CREDENCIAIS = {
    "host": "db.cliente.pt",
    "port": 5432,
    "username": "leitor",
    "password": "segredo-muito-secreto",
    "database": "vendas",
}


@pytest.fixture
def com_chave(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def sem_chave(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)


# ── 2. Falhar fechado sem chave ─────────────────────────────────────────


@pytest.mark.parametrize("ambiente", ["production", "staging", "qualquer-outro", ""])
def test_sem_chave_fora_de_dev_recusa_gravar(sem_chave, monkeypatch, ambiente):
    monkeypatch.setattr(settings, "ENVIRONMENT", ambiente)
    with pytest.raises(EncryptionKeyMissingError) as exc:
        encrypt_dict(dict(CREDENCIAIS))
    assert exc.value.status_code == 503
    # A mensagem não leva a config.
    assert "segredo" not in exc.value.message


@pytest.mark.parametrize("ambiente", ["development", "test"])
def test_sem_chave_em_dev_grava_em_claro_com_aviso(sem_chave, monkeypatch, caplog, ambiente):
    monkeypatch.setattr(settings, "ENVIRONMENT", ambiente)
    with caplog.at_level("WARNING", logger=encryption.logger.name):
        out = encrypt_dict(dict(CREDENCIAIS))
    assert out == CREDENCIAIS
    assert any("PLAINTEXT" in r.getMessage() for r in caplog.records)


def test_com_chave_cifra_e_e_idempotente(com_chave, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    blob = encrypt_dict(dict(CREDENCIAIS))
    assert is_encrypted(blob)
    assert "segredo" not in str(blob)
    assert decrypt_dict(blob) == CREDENCIAIS
    # Cifrar o que já está cifrado não embrulha outra vez.
    assert encrypt_dict(blob) == blob


def test_erro_a_cifrar_levanta_em_vez_de_gravar_em_claro(com_chave):
    with pytest.raises(TypeError):
        encrypt_dict({"x": object()})  # não serializável


# ── 1. PATCH cifra e não perde chaves ──────────────────────────────────


async def _ligacao(db, config: dict) -> tuple[User, DataConnection]:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@exemplo.pt",
        role="admin",
        password_hash="x",
        name="Teste",
    )
    db.add(user)
    await db.flush()
    conn = DataConnection(
        id=uuid.uuid4(),
        name="Vendas",
        connector_id="postgresql",
        config=config,
        sync_frequency="manual",
        status="active",
        created_by=user.id,
    )
    db.add(conn)
    await db.commit()
    return user, conn


async def _config_gravada(db, cid) -> dict:
    db.expire_all()
    return (
        await db.execute(select(DataConnection.config).where(DataConnection.id == cid))
    ).scalar_one()


@pytest.mark.asyncio
async def test_patch_com_config_grava_cifrado_e_mantem_as_outras_chaves(db_session, com_chave):
    user, conn = await _ligacao(db_session, encrypt_dict(dict(CREDENCIAIS)))
    service = ConnectionService(db_session)

    with patch("src.services._mutation_guard.require_mutation_rights", new=AsyncMock()):
        resp = await service.update_connection(
            conn.id, user, ConnectionUpdate(config={"database": "vendas_2026"})
        )

    gravada = await _config_gravada(db_session, conn.id)
    assert is_encrypted(gravada), "a config do PATCH foi gravada em claro"
    assert "segredo" not in str(gravada)
    decifrada = decrypt_dict(gravada)
    assert decifrada["database"] == "vendas_2026"
    # O PATCH parcial não apaga a password nem o resto.
    assert decifrada["password"] == "segredo-muito-secreto"
    assert decifrada["host"] == "db.cliente.pt"
    # E a resposta nunca devolve credenciais.
    dump = resp.model_dump_json()
    assert "segredo" not in dump and "__encrypted" not in dump
    assert "config" not in resp.model_dump()


@pytest.mark.asyncio
async def test_patch_sobre_config_legada_em_claro_passa_a_cifrada(db_session, com_chave):
    user, conn = await _ligacao(db_session, dict(CREDENCIAIS))
    service = ConnectionService(db_session)
    with patch("src.services._mutation_guard.require_mutation_rights", new=AsyncMock()):
        await service.update_connection(
            conn.id, user, ConnectionUpdate(config={"selected_tables": ["public.vendas"]})
        )
    decifrada = decrypt_dict(await _config_gravada(db_session, conn.id))
    assert decifrada == {**CREDENCIAIS, "selected_tables": ["public.vendas"]}


@pytest.mark.asyncio
async def test_patch_nao_aceita_um_blob_vindo_de_fora(db_session, com_chave):
    user, conn = await _ligacao(db_session, encrypt_dict(dict(CREDENCIAIS)))
    service = ConnectionService(db_session)
    with patch("src.services._mutation_guard.require_mutation_rights", new=AsyncMock()):
        await service.update_connection(
            conn.id, user, ConnectionUpdate(config={"__encrypted": "lixo", "port": 6543})
        )
    decifrada = decrypt_dict(await _config_gravada(db_session, conn.id))
    assert decifrada["port"] == 6543
    assert decifrada["password"] == "segredo-muito-secreto"
    assert "__encrypted" not in decifrada


@pytest.mark.asyncio
async def test_patch_recusa_se_a_config_guardada_nao_decifra(db_session, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    blob_de_outra_chave = encrypt_dict(dict(CREDENCIAIS))
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    user, conn = await _ligacao(db_session, blob_de_outra_chave)
    service = ConnectionService(db_session)
    with patch("src.services._mutation_guard.require_mutation_rights", new=AsyncMock()):
        with pytest.raises(Exception) as exc:
            await service.update_connection(conn.id, user, ConnectionUpdate(config={"port": 1}))
    assert getattr(exc.value, "status_code", None) == 503
    # Ficou exactamente como estava.
    assert await _config_gravada(db_session, conn.id) == blob_de_outra_chave


@pytest.mark.asyncio
async def test_patch_sem_chave_em_producao_recusa_e_nao_grava(db_session, monkeypatch):
    user, conn = await _ligacao(db_session, dict(CREDENCIAIS))
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    service = ConnectionService(db_session)
    with patch("src.services._mutation_guard.require_mutation_rights", new=AsyncMock()):
        with pytest.raises(EncryptionKeyMissingError):
            await service.update_connection(
                conn.id, user, ConnectionUpdate(config={"password": "nova"})
            )
    assert (await _config_gravada(db_session, conn.id))["password"] == "segredo-muito-secreto"


# ── 3. selected_tables sobre a config cifrada ──────────────────────────


@pytest.mark.asyncio
async def test_sync_aplica_selected_tables_com_config_cifrada(db_session, com_chave):
    config = {**CREDENCIAIS, "selected_tables": ["public.vendas"]}
    user, conn = await _ligacao(db_session, encrypt_dict(config))
    cid = conn.id

    conector = SimpleNamespace(
        get_metadata=AsyncMock(
            return_value={
                "tables": [
                    {"name": "vendas", "schema": "public", "columns": []},
                    {"name": "salarios", "schema": "public", "columns": []},
                ],
                "schemas": ["public"],
            }
        )
    )
    service = ConnectionService(db_session)
    with (
        patch("src.services.connection_service.get_connector", return_value=conector),
        patch.object(service, "_assert_user_can_access_connection", new=AsyncMock()),
    ):
        await service.sync_connection(cid, user)

    # O conector recebeu a config decifrada.
    assert conector.get_metadata.await_args.args[0]["password"] == "segredo-muito-secreto"
    db_session.expire_all()
    meta = (
        await db_session.execute(
            select(ConnectionMetadata).where(ConnectionMetadata.connection_id == cid)
        )
    ).scalar_one()
    nomes = [t["name"] for t in meta.tables]
    assert nomes == ["vendas"], f"o filtro não se aplicou: {nomes}"


# ── 4. Script de migração ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_script_detecta_em_dry_run_e_cifra_com_apply(db_session, com_chave, capsys):
    from scripts.cifrar_configs_em_claro import tratar_base

    _, c1 = await _ligacao(db_session, dict(CREDENCIAIS))
    _, c2 = await _ligacao(db_session, encrypt_dict(dict(CREDENCIAIS)))
    em_claro_id, cifrada_id = c1.id, c2.id
    blob_original = await _config_gravada(db_session, cifrada_id)

    # Dry-run: encontra, não escreve.
    r = await tratar_base(db_session, aplicar=False)
    assert r.em_claro == [str(em_claro_id)]
    assert r.ja_cifradas == 1 and r.cifradas == []
    assert (await _config_gravada(db_session, em_claro_id)) == CREDENCIAIS

    # Apply: cifra a que estava em claro, não toca na outra.
    r = await tratar_base(db_session, aplicar=True)
    assert r.cifradas == [str(em_claro_id)] and r.falhadas == []
    nova = await _config_gravada(db_session, em_claro_id)
    assert is_encrypted(nova) and decrypt_dict(nova) == CREDENCIAIS
    assert (await _config_gravada(db_session, cifrada_id)) == blob_original

    # Idempotente: segunda passagem não tem nada para fazer.
    r = await tratar_base(db_session, aplicar=True)
    assert r.em_claro == [] and r.ja_cifradas == 2

    # Nunca imprime valores.
    assert "segredo" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_script_recusa_correr_sem_chave(sem_chave, capsys):
    from scripts.cifrar_configs_em_claro import correr

    with patch("src.workers.por_cada_cliente.clientes_activos", new=AsyncMock()) as listar:
        codigo = await correr(aplicar=True)
    assert codigo == 2
    listar.assert_not_awaited()
    assert "ENCRYPTION_KEY" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_script_percorre_cada_cliente(com_chave, capsys):
    """Usa os ajudantes por cliente e reporta um que falhe sem parar os outros."""
    import contextlib

    from scripts import cifrar_configs_em_claro as mod
    from scripts.cifrar_configs_em_claro import Resultado

    vistos = []

    @contextlib.asynccontextmanager
    async def contexto(slug):
        vistos.append(slug)
        yield slug != "partido"

    @contextlib.asynccontextmanager
    async def sessao(_ctx):
        yield object()

    async def tratar(_db, aplicar):
        return Resultado(total=1, em_claro=["id-1"], cifradas=["id-1"] if aplicar else [])

    with (
        patch(
            "src.workers.por_cada_cliente.clientes_activos",
            new=AsyncMock(return_value=["default", "sandbox", "partido"]),
        ),
        patch("src.workers.por_cada_cliente.contexto_do_cliente", new=contexto),
        patch(
            "src.config.tenant_connection_manager.tenant_connection_manager.session_for",
            new=sessao,
        ),
        patch.object(mod, "tratar_base", new=tratar),
    ):
        codigo = await mod.correr(aplicar=False)

    assert vistos == ["default", "sandbox", "partido"]
    out = capsys.readouterr().out
    assert "[partido] não resolveu" in out
    assert "em_claro=2" in out
    assert codigo == 1  # uma base falhou → não sai a 0


# ── 5. Erros do sky-ai nos registos ────────────────────────────────────


def test_texto_para_log_redige_e_corta():
    from src.utils.log_redaction import texto_para_log

    corpo = (
        '{"detail": "column \\"nif\\" does not exist", "sql": '
        "\"SELECT * FROM clientes WHERE email = 'ana@cliente.pt' AND nif = '518824985' "
        'AND total > 19994.92"}'
    )
    out = texto_para_log(corpo)
    assert "ana@cliente.pt" not in out
    assert "518824985" not in out
    assert "19994" not in out
    assert "does not exist" in out  # a forma do erro fica
    assert len(texto_para_log("x" * 5000)) < 340


def test_ai_service_nao_regista_o_corpo_cru():
    from pathlib import Path

    fonte = (Path(__file__).resolve().parents[1] / "services" / "ai_service.py").read_text(
        encoding="utf-8"
    )
    assert (
        'logger.error(f"AI service HTTP error: {e.response.status_code} - {e.response.text}")'
        not in fonte
    )
