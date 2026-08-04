"""Shared HTTP acceptance helpers (G0, Sky Mobile gap-closure).

The masterplan §14 global test conventions require, on every protected
endpoint: the **auth matrix** (no token / malformed token / expired access
token → 401) and, on tenant-scoped endpoints, **cross-tenant isolation**.

These helpers turn those checks into one-liners so each ticket's acceptance
suite asserts them without copy-pasting the same requests. The "valid token"
and "other tenant" arms stay in the ticket's own scenario tests, because the
expected success shape / scoping is endpoint-specific.
"""

from __future__ import annotations

from typing import Optional


def bearer(token: str) -> dict:
    """Authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


async def assert_auth_matrix(
    async_client,
    method: str,
    path: str,
    *,
    expired_token: str,
    invalid_token: str,
    json: Optional[dict] = None,
) -> None:
    """Assert the three unauthenticated arms of the auth matrix all 401.

    Args:
        async_client: the httpx AsyncClient fixture.
        method: HTTP verb, e.g. "GET" / "POST".
        path: full path under the app, e.g. "/api/v1/auth/me".
        expired_token: a well-formed but expired access token (fixture).
        invalid_token: a malformed / unsigned token string (fixture).
        json: optional request body for mutating endpoints.
    """
    # 1. No Authorization header at all.
    r = await async_client.request(method, path, json=json)
    assert r.status_code == 401, f"{method} {path} no-token → {r.status_code}, want 401"

    # 2. Malformed / unsigned token.
    r = await async_client.request(method, path, json=json, headers=bearer(invalid_token))
    assert r.status_code == 401, f"{method} {path} bad-token → {r.status_code}, want 401"

    # 3. Well-formed but expired access token.
    r = await async_client.request(method, path, json=json, headers=bearer(expired_token))
    assert r.status_code == 401, f"{method} {path} expired-token → {r.status_code}, want 401"
