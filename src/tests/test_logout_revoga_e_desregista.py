"""POST /auth/logout: revoga o refresh token e desregista o push do aparelho.

A app passa a chamar o logout ao «Cerrar sesión». Sem o `push_token` no
corpo, um telemóvel partilhado continuava a receber os pushes da pessoa
anterior — e o refresh token ficava válido no servidor.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.core.security import create_refresh_token
from src.models.device import Device


@pytest.mark.asyncio
async def test_logout_revoga_refresh_e_remove_so_o_push_indicado(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    user = test_user_with_tokens["user"]
    db_session.add_all(
        [
            Device(user_id=user.id, platform="ios", push_token="ExponentPushToken[este]"),
            Device(user_id=user.id, platform="android", push_token="ExponentPushToken[outro]"),
        ]
    )
    await db_session.commit()

    with patch("src.core.token_blocklist.revoke_user_tokens", new=AsyncMock()) as revoga:
        r = await async_client.post(
            "/api/v1/auth/logout",
            json={
                "refresh_token": test_user_with_tokens["refresh_token"],
                "push_token": "ExponentPushToken[este]",
            },
        )
    assert r.status_code == 200, r.text
    revoga.assert_awaited_once()
    assert revoga.await_args.args[0] == str(user.id)

    tokens = (
        await db_session.execute(select(Device.push_token).where(Device.user_id == user.id))
    ).scalars().all()
    assert list(tokens) == ["ExponentPushToken[outro]"]

    # O refresh token deixou de servir.
    r2 = await async_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": test_user_with_tokens["refresh_token"]}
    )
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_logout_com_token_forjado_nao_toca_noutra_pessoa(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    """Um refresh token com o `sub` de outra pessoa mas assinatura errada não
    revoga as sessões dela nem apaga os aparelhos dela."""
    from jose import jwt

    vitima = test_user_with_tokens["user"]
    db_session.add(Device(user_id=vitima.id, platform="ios", push_token="ExponentPushToken[v]"))
    await db_session.commit()

    forjado = jwt.encode({"sub": str(vitima.id), "type": "refresh"}, "outra-chave", "HS256")
    with patch("src.core.token_blocklist.revoke_user_tokens", new=AsyncMock()) as revoga:
        r = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": forjado, "push_token": "ExponentPushToken[v]"},
        )
    assert r.status_code == 200
    revoga.assert_not_awaited()
    restantes = (
        await db_session.execute(select(Device.push_token).where(Device.user_id == vitima.id))
    ).scalars().all()
    assert list(restantes) == ["ExponentPushToken[v]"]


@pytest.mark.asyncio
async def test_logout_sem_push_token_continua_a_funcionar(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    with patch("src.core.token_blocklist.revoke_user_tokens", new=AsyncMock()):
        r = await async_client.post(
            "/api/v1/auth/logout", json={"refresh_token": test_user_with_tokens["refresh_token"]}
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_logout_refresh_valido_mas_ja_fora_da_base_ainda_desregista(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session
):
    """Um refresh assinado por nós (p.ex. já rodado) prova a identidade
    mesmo sem linha na base: o aparelho sai na mesma."""
    user = test_user_with_tokens["user"]
    db_session.add(Device(user_id=user.id, platform="ios", push_token="ExponentPushToken[x]"))
    await db_session.commit()
    rodado = create_refresh_token({"sub": str(user.id)})
    with patch("src.core.token_blocklist.revoke_user_tokens", new=AsyncMock()):
        r = await async_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": rodado, "push_token": "ExponentPushToken[x]"},
        )
    assert r.status_code == 200
    restantes = (
        await db_session.execute(select(Device.push_token).where(Device.user_id == user.id))
    ).scalars().all()
    assert list(restantes) == []
