"""Autoeliminação desligada — a conta é da organização (decisão de 15/10/2026).

`POST /privacy/account/delete` existia para a regra 5.1.1(v) da Apple, que só
se aplica a apps que criam contas. A Sky não cria: a conta é criada e
removida pela organização do cliente. Um utilizador que se apagava pela API
contrariava a página pública de eliminação e o que a app diz.

O que tem de ser verdade:

* o utilizador normal recebe 403, com a frase na língua dele, e **nada é
  apagado**;
* o administrador da organização continua a conseguir apagar outra pessoa
  (`POST /privacy/dsar/delete`).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.user import User
from src.repositories.user import UserRepository

URL = "/api/v1/privacy/account/delete"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _membro(db_session: AsyncSession, email: str, preferences: dict | None = None):
    user = await UserRepository(db_session).create(
        email=email,
        password_hash=get_password_hash("x-password-123"),
        name="Membro",
        role="member",
    )
    if preferences is not None:
        user.preferences = preferences
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return user, token


async def _ainda_existe(db_session: AsyncSession, user_id) -> User:
    db_session.expire_all()
    row = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()
    return row


@pytest.mark.asyncio
async def test_sem_sessao_e_401(async_client: AsyncClient):
    resp = await async_client.post(URL, json={"confirm": True})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_utilizador_normal_recebe_403_e_nada_e_apagado(
    async_client: AsyncClient, db_session: AsyncSession
):
    user, token = await _membro(db_session, "membro.pt@exemplo.pt")
    email_antes = user.email

    resp = await async_client.post(URL, headers=_auth(token), json={"confirm": True})

    assert resp.status_code == 403, resp.text
    erro = resp.json()["error"]
    assert erro["code"] == "FORBIDDEN"
    assert erro["details"]["reason"] == "conta_gerida_pela_organizacao"
    assert set(erro["details"]["messages"]) == {"pt", "es", "en"}
    assert "gerida pela sua organização" in erro["message"]  # pt por omissão

    row = await _ainda_existe(db_session, user.id)
    assert row.deleted_at is None
    assert row.email == email_antes


@pytest.mark.asyncio
async def test_a_frase_segue_a_lingua_de_quem_pede(
    async_client: AsyncClient, db_session: AsyncSession
):
    _, token_es = await _membro(db_session, "membro.es@exemplo.es", {"language": "es"})
    r = await async_client.post(URL, headers=_auth(token_es), json={"confirm": True})
    assert r.status_code == 403
    assert "la gestiona su organización" in r.json()["error"]["message"]

    _, token_en = await _membro(db_session, "member.en@example.com")
    r = await async_client.post(
        URL,
        headers={**_auth(token_en), "Accept-Language": "en-GB,en;q=0.9"},
        json={"confirm": True},
    )
    assert r.status_code == 403
    assert "managed by your organization" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_nem_o_administrador_se_apaga_a_si_proprio_por_aqui(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    """O caminho do admin é outro (`/privacy/dsar/delete`); este fecha para todos."""
    admin = test_user_with_tokens["user"]
    resp = await async_client.post(
        URL, headers=_auth(test_user_with_tokens["access_token"]), json={"confirm": True}
    )
    assert resp.status_code == 403
    assert (await _ainda_existe(db_session, admin.id)).deleted_at is None


@pytest.mark.asyncio
async def test_admin_da_organizacao_continua_a_apagar_outra_pessoa(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    alvo, _ = await _membro(db_session, "a.sair@exemplo.pt")

    resp = await async_client.post(
        "/api/v1/privacy/dsar/delete",
        headers=_auth(test_user_with_tokens["access_token"]),
        json={"user_email": "a.sair@exemplo.pt", "confirm": True},
    )
    assert resp.status_code == 200, resp.text

    row = await _ainda_existe(db_session, alvo.id)
    assert row.deleted_at is not None  # soft-deleted
    assert row.email.endswith("@deleted.local")  # anonymized


@pytest.mark.asyncio
async def test_membro_nao_apaga_outra_pessoa(async_client: AsyncClient, db_session: AsyncSession):
    alvo, _ = await _membro(db_session, "alvo@exemplo.pt")
    _, token = await _membro(db_session, "curioso@exemplo.pt")
    resp = await async_client.post(
        "/api/v1/privacy/dsar/delete",
        headers=_auth(token),
        json={"user_email": "alvo@exemplo.pt", "confirm": True},
    )
    assert resp.status_code == 403
    assert (await _ainda_existe(db_session, alvo.id)).deleted_at is None
