"""Dedicated rate-limit bucket for the Console surface (Gap #2).

The middleware now splits the Redis keyspace and the per-minute / per-
hour budgets between regular tenant traffic and Console operator
traffic. These tests pin the routing decision without spinning up a
real Redis: we stub ``get_redis`` with an in-memory counter dict and
verify that requests under ``/api/console/v1/*`` increment a different
key than requests against the tenant API, and that hitting the
Console-specific cap returns 429.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from src.api.middleware.rate_limit import rate_limit_middleware


class _FakeRedis:
    """Just enough Redis surface for the middleware to run end-to-end."""

    def __init__(self) -> None:
        self.counts: Dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:  # noqa: D401
        return None


def _build_app(fake_redis: _FakeRedis) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(rate_limit_middleware)

    @app.get("/api/console/v1/dashboard")
    async def console_dash():  # noqa: D401
        return {"ok": True}

    @app.get("/api/v1/agents/")
    async def list_agents():  # noqa: D401
        return {"ok": True}

    async def _stub_get_redis():
        return fake_redis

    import src.api.middleware.rate_limit as mod

    mod.get_redis = _stub_get_redis  # type: ignore[assignment]
    return app


def _disable_strict_limits(monkeypatch, *, console_min=10, regular_min=10) -> None:
    """Lower limits so tests don't have to fire 300 requests."""
    from src.config.settings import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", regular_min)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 10_000)
    monkeypatch.setattr(settings, "CONSOLE_RATE_LIMIT_PER_MINUTE", console_min)
    monkeypatch.setattr(settings, "CONSOLE_RATE_LIMIT_PER_HOUR", 10_000)


def test_console_path_uses_console_bucket_key(monkeypatch):
    fake = _FakeRedis()
    _disable_strict_limits(monkeypatch)
    app = _build_app(fake)
    client = TestClient(app)
    r = client.get("/api/console/v1/dashboard")
    assert r.status_code == 200
    # The minute key for an unauthenticated request lives under the IP
    # bucket; the prefix should be ``rate_limit:console`` not
    # ``rate_limit:`` so the customer-facing quota is unaffected.
    assert any(
        k.startswith("rate_limit:console:minute:") for k in fake.counts
    ), f"expected console bucket key, got {list(fake.counts)}"
    assert not any(
        k.startswith("rate_limit:minute:") and ":console" not in k for k in fake.counts
    )


def test_regular_path_uses_default_bucket_key(monkeypatch):
    fake = _FakeRedis()
    _disable_strict_limits(monkeypatch)
    app = _build_app(fake)
    client = TestClient(app)
    r = client.get("/api/v1/agents/")
    assert r.status_code == 200
    assert any(
        k.startswith("rate_limit:minute:") for k in fake.counts
    ), f"expected default bucket key, got {list(fake.counts)}"
    assert not any(k.startswith("rate_limit:console:") for k in fake.counts)


def test_console_bucket_returns_429_when_exceeded(monkeypatch):
    fake = _FakeRedis()
    _disable_strict_limits(monkeypatch, console_min=2, regular_min=1000)
    app = _build_app(fake)
    client = TestClient(app)
    # Two calls within the cap.
    assert client.get("/api/console/v1/dashboard").status_code == 200
    assert client.get("/api/console/v1/dashboard").status_code == 200
    # Third call breaches the per-minute cap.
    r = client.get("/api/console/v1/dashboard")
    assert r.status_code == 429
    body = r.json()
    assert "Console" in body["message"]


def test_console_breach_does_not_consume_regular_budget(monkeypatch):
    """A Console script gone wild must not 429 customer requests."""
    fake = _FakeRedis()
    _disable_strict_limits(monkeypatch, console_min=1, regular_min=1000)
    app = _build_app(fake)
    client = TestClient(app)
    # Burn the Console bucket.
    client.get("/api/console/v1/dashboard")
    client.get("/api/console/v1/dashboard")  # 429
    # Customer-facing request still answered.
    assert client.get("/api/v1/agents/").status_code == 200
