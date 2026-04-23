"""Regression for CR-001 (red-team finding 2026-04-23).

Before fix: DELETE /api/v1/strategy/pillars/{id} returned 204 for any
authenticated user, allowing cross-user destruction of Personal-scope
pillars. Same hole applied to update + to /objectives + /okrs.

These tests lock the fix (``StrategyService._require_personal_owner``)
long-term even if the red-team repo goes quiet.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_user_b_cannot_delete_user_a_personal_pillar(
    async_client: AsyncClient,
    test_user_with_tokens: dict,
    test_second_user_with_tokens: dict,
):
    a_headers = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    b_headers = {"Authorization": f"Bearer {test_second_user_with_tokens['access_token']}"}

    # A seeds a Personal pillar.
    create = await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "A-only pillar"},
        headers=a_headers,
    )
    assert create.status_code == 201, create.text
    pillar_id = create.json()["id"]

    # B tries to delete it — must 404 (we don't 403 to avoid existence
    # oracle).
    delete_as_b = await async_client.delete(
        f"/api/v1/strategy/pillars/{pillar_id}",
        headers=b_headers,
    )
    assert delete_as_b.status_code in (403, 404), (
        f"Cross-user delete accepted (status {delete_as_b.status_code}). "
        "Regression on CR-001."
    )

    # And A can still read it back in the tree.
    tree = await async_client.get(
        "/api/v1/strategy/tree?is_personal=true",
        headers=a_headers,
    )
    assert tree.status_code == 200
    ids = [p["id"] for p in (tree.json().get("pillars") or [])]
    assert pillar_id in ids, "A lost their own pillar — defence misfired"


@pytest.mark.asyncio
async def test_user_b_cannot_update_user_a_personal_pillar(
    async_client: AsyncClient,
    test_user_with_tokens: dict,
    test_second_user_with_tokens: dict,
):
    a_headers = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    b_headers = {"Authorization": f"Bearer {test_second_user_with_tokens['access_token']}"}

    create = await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "A-only update target"},
        headers=a_headers,
    )
    assert create.status_code == 201
    pillar_id = create.json()["id"]

    # PUT, not PATCH — the update_pillar route is registered as PUT.
    r = await async_client.put(
        f"/api/v1/strategy/pillars/{pillar_id}",
        json={"name": "hijacked by B"},
        headers=b_headers,
    )
    assert r.status_code in (403, 404), (
        f"Cross-user update accepted (status {r.status_code})"
    )


@pytest.mark.asyncio
async def test_user_a_can_still_delete_their_own_pillar(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Defence-in-depth sometimes over-fires. Positive control."""
    a_headers = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    create = await async_client.post(
        "/api/v1/strategy/pillars?is_personal=true",
        json={"name": "canary"},
        headers=a_headers,
    )
    assert create.status_code == 201
    pillar_id = create.json()["id"]
    r = await async_client.delete(
        f"/api/v1/strategy/pillars/{pillar_id}", headers=a_headers
    )
    assert r.status_code == 204, f"Owner can't delete their own pillar ({r.status_code})"
