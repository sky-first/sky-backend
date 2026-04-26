"""Tests for the /api/v1/db-health admin-only endpoint.

Pairs with the Postgres pool hardening rollout — these lock in two
behaviours we don't want to regress:

  * Authenticated non-admins get 403 (the panel exposes config
    snapshots that ops cares about, we don't want to leak them).
  * The happy-path response has the expected schema with `ok=true` and
    a `config` block that mirrors the new settings.

The pool counters are checked for *presence* only, not exact values,
because in SQLite test mode SQLAlchemy uses NullPool and the counters
degrade to an empty dict.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_db_health_returns_ok_for_admin(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Default fixture user is created with role='admin' (see conftest).
    The endpoint should return ``ok=true`` with a populated config block.
    """
    headers = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    resp = await async_client.get("/api/v1/db-health/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["ping_ms"], (int, float))
    config = body["config"]
    # Keys ops dashboards pin against — order doesn't matter.
    expected_keys = {
        "pool_size",
        "max_overflow",
        "pool_timeout",
        "pool_pre_ping",
        "pool_use_lifo",
        "statement_timeout_ms",
        "idle_in_tx_timeout_ms",
        "lock_timeout_ms",
        "pgbouncer_mode",
    }
    assert expected_keys.issubset(config.keys())
    # Sanity: timeouts are positive integers, pgbouncer is bool.
    assert config["pool_timeout"] > 0
    assert config["statement_timeout_ms"] > 0
    assert isinstance(config["pgbouncer_mode"], bool)


@pytest.mark.asyncio
async def test_db_health_forbidden_for_non_admin(
    async_client: AsyncClient,
    test_user_with_tokens: dict,
    db_session,
):
    """Demote the test user, then verify the endpoint refuses them."""
    user = test_user_with_tokens["user"]
    user.role = "navigator"
    db_session.add(user)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {test_user_with_tokens['access_token']}"}
    resp = await async_client.get("/api/v1/db-health/", headers=headers)
    assert resp.status_code == 403, resp.text
