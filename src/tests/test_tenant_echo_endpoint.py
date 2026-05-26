"""Tests for ``/api/v1/_test/tenant-echo`` and ``tenant-db-ping``
(Projeto A — PR #5).

These tests run via the FastAPI ``TestClient`` and exercise the whole
middleware stack. They are the first place where the full pipeline
auth → tenant_resolver → handler is checked together.

The endpoints are public (in the auth allow-list) so no token is
needed; they also rely on ``MULTI_TENANT_ENABLED`` being False to fall
through to the default context — flipping the flag would require us
to seed the registry on the global engine, which is out of scope for
a smoke endpoint test.
"""

from __future__ import annotations

import pytest

from src.config.settings import settings


def test_tenant_echo_returns_default_context_when_flag_off(client):
    response = client.get("/api/v1/_test/tenant-echo")
    assert response.status_code == 200
    body = response.json()

    assert body["multi_tenant_enabled"] is False
    assert body["tenant"]["slug"] == "default"
    assert body["tenant"]["is_default"] is True
    assert body["resolved_from"] == "default"


def test_tenant_echo_payload_shape(client):
    """Pin the shape so frontend devs can rely on it."""
    response = client.get("/api/v1/_test/tenant-echo")
    body = response.json()
    tenant = body["tenant"]

    expected_keys = {
        "slug",
        "id",
        "tier",
        "display_name",
        "is_default",
        "is_active",
        "rate_limit_rpm",
        "rate_limit_tpm",
        "db_host",
        "db_name",
        "redis_host",
        "bedrock_inference_profile_arn",
        "has_db_credentials_secret",
        "has_redis_credentials_secret",
        "feature_flags",
        "capacity_limits",
    }
    assert expected_keys.issubset(tenant.keys())


def test_tenant_echo_does_not_leak_secret_arns(client):
    response = client.get("/api/v1/_test/tenant-echo")
    body = response.json()
    # The default context has empty ARN strings — but make sure the
    # response shape never exposes them as plain text fields.
    tenant = body["tenant"]
    assert "db_credentials_secret_arn" not in tenant
    assert "redis_credentials_secret_arn" not in tenant
    # The "has_*" booleans are the only signal we expose.
    assert tenant["has_db_credentials_secret"] is False
    assert tenant["has_redis_credentials_secret"] is False


def test_tenant_db_ping_returns_1(client):
    response = client.get("/api/v1/_test/tenant-db-ping")
    assert response.status_code == 200
    body = response.json()
    assert body["select_1"] == 1
    assert body["pool"] == "global"  # default tenant → global pool
    assert body["tenant_slug"] == "default"


def test_tenant_db_ping_does_not_create_tenant_pool_for_default(client):
    """Default tenant must NOT spin up a per-tenant engine."""
    response = client.get("/api/v1/_test/tenant-db-ping")
    body = response.json()
    assert body["known_tenant_pools"] == []


def test_endpoints_are_public(client):
    """No Authorization header — both must still return 200."""
    assert client.get("/api/v1/_test/tenant-echo").status_code == 200
    assert client.get("/api/v1/_test/tenant-db-ping").status_code == 200


@pytest.mark.asyncio
async def test_resolution_signal_reports_header_when_used(client, monkeypatch):
    """With the flag ON and a slug header, the signal should be 'header'.

    We can't actually resolve a real tenant through the global engine
    in the test client (the registry table is on the test engine, not
    the global one), so this asserts the failure mode: flag ON, slug
    supplied but unknown → 404. Confirms the middleware is wired.
    """
    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)

    response = client.get(
        "/api/v1/_test/tenant-echo",
        headers={"X-Tenant-Slug": "this-slug-does-not-exist"},
    )
    # Middleware spec'd to 404 on unknown slug when the flag is ON.
    assert response.status_code == 404
    body = response.json()
    assert body.get("error") == "tenant_not_found"
