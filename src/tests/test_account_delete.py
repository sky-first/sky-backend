"""Self-service account deletion (App Store 5.1.1(v) / GDPR Art. 17).

The authenticated user erases their own account from POST
/privacy/account/delete — no admin, no support ticket.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_delete_requires_confirm(async_client: AsyncClient, test_user_with_tokens: dict):
    resp = await async_client.post(
        "/api/v1/privacy/account/delete",
        headers=_auth(test_user_with_tokens["access_token"]),
        json={"confirm": False},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_unauthenticated(async_client: AsyncClient):
    resp = await async_client.post("/api/v1/privacy/account/delete", json={"confirm": True})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_erases_own_account(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    resp = await async_client.post(
        "/api/v1/privacy/account/delete",
        headers=_auth(test_user_with_tokens["access_token"]),
        json={"confirm": True},
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(select(User).where(User.id == user.id))
    ).scalar_one_or_none()
    assert row is not None
    assert row.deleted_at is not None  # soft-deleted
    assert row.email.endswith("@deleted.local")  # anonymized
