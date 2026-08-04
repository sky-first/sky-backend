"""G0 · Smoke test for the shared HTTP acceptance harness.

Proves assert_auth_matrix works against a real protected endpoint, and that a
valid token still passes — so every ticket suite can rely on it.
"""

from __future__ import annotations

import pytest

from src.tests.acceptance_helpers import assert_auth_matrix, bearer


@pytest.mark.asyncio
async def test_auth_matrix_rejects_unauthenticated(async_client, expired_token, invalid_token):
    # /auth/me is a plain protected GET — the canonical probe.
    await assert_auth_matrix(
        async_client,
        "GET",
        "/api/v1/auth/me",
        expired_token=expired_token,
        invalid_token=invalid_token,
    )


@pytest.mark.asyncio
async def test_valid_token_passes(async_client, valid_access_token, test_user):
    r = await async_client.get("/api/v1/auth/me", headers=bearer(valid_access_token))
    assert r.status_code == 200
    assert r.json()["email"] == test_user["email"]
