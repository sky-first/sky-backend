"""Device registry endpoint tests (BE-06 · T-06.1/.2/.10/.11/.12).

The registry is the first half of push: register a token, keep it unique
per (user, token) across relaunches, and drop it on logout. Sending +
fan-out + prune are covered in test_push_dispatch.py.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import Device


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _count_devices(db: AsyncSession, user_id) -> int:
    rows = (await db.execute(select(Device).where(Device.user_id == user_id))).scalars().all()
    return len(rows)


# ─── T-06.1 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_register_device_creates_one_row(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    resp = await async_client.post(
        "/api/v1/devices",
        json={"platform": "ios", "push_token": "ExponentPushToken[abc]"},
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["platform"] == "ios"
    assert body["push_token"] == "ExponentPushToken[abc]"
    assert await _count_devices(db_session, user.id) == 1


# ─── T-06.2 ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reregister_same_token_upserts(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    payload = {"platform": "ios", "push_token": "tok-relaunch"}
    h = _auth(test_user_with_tokens["access_token"])

    first = await async_client.post("/api/v1/devices", json=payload, headers=h)
    # App relaunches and registers again — possibly with a platform change.
    payload2 = {"platform": "android", "push_token": "tok-relaunch"}
    second = await async_client.post("/api/v1/devices", json=payload2, headers=h)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]  # same row
    assert second.json()["platform"] == "android"  # refreshed
    assert await _count_devices(db_session, user.id) == 1  # no duplicate


# ─── T-06.10 ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_register_bad_platform_422(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    resp = await async_client.post(
        "/api/v1/devices",
        json={"platform": "windows", "push_token": "tok"},
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_token_422(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    resp = await async_client.post(
        "/api/v1/devices",
        json={"platform": "ios"},
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 422


# ─── T-06.11 ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_register_unauthenticated_401(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/devices",
        json={"platform": "ios", "push_token": "tok"},
    )
    assert resp.status_code == 401


# ─── T-06.12 ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unregister_removes_token(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    h = _auth(test_user_with_tokens["access_token"])
    await async_client.post(
        "/api/v1/devices",
        json={"platform": "ios", "push_token": "tok-logout"},
        headers=h,
    )
    assert await _count_devices(db_session, user.id) == 1

    resp = await async_client.delete("/api/v1/devices/tok-logout", headers=h)
    assert resp.status_code == 204
    assert await _count_devices(db_session, user.id) == 0
