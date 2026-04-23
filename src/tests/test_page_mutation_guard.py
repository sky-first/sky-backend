"""Regression for HI-003 (red-team 2026-04-23).

Before fix: Space-scoped pages could only be deleted by the owner.
Space admins couldn't delete a page another user created in the
same space — broke the product rule "Space admin can manage
anything in their Space".

Fix: Personal pages stay owner-only. Space pages: owner-OR-RBAC
pages.delete via RBACService (commander + admin pass; explorer
and navigator denied).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_user_b_cannot_delete_user_a_personal_page(
    async_client: AsyncClient,
    test_user_with_tokens: dict,
    test_second_user_with_tokens: dict,
):
    a_h = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    b_h = {"Authorization": f"Bearer {test_second_user_with_tokens['access_token']}"}

    create = await async_client.post(
        "/api/v1/pages",
        json={"name": "A personal page", "type": "personal", "color": "#fff"},
        headers=a_h,
    )
    assert create.status_code == 201, create.text
    page_id = create.json()["id"]

    # B tries to delete → must be rejected.
    r = await async_client.delete(f"/api/v1/pages/{page_id}", headers=b_h)
    assert r.status_code in (403, 404), (
        f"Personal page delete leaked cross-user ({r.status_code})"
    )


@pytest.mark.asyncio
async def test_page_owner_can_delete_their_own(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    h = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    create = await async_client.post(
        "/api/v1/pages",
        json={"name": "own-delete-canary", "type": "personal", "color": "#fff"},
        headers=h,
    )
    assert create.status_code == 201
    page_id = create.json()["id"]
    r = await async_client.delete(f"/api/v1/pages/{page_id}", headers=h)
    assert r.status_code in (200, 204)
