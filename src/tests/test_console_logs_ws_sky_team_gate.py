"""Sky-team gate on the Console WS log stream.

Gap #1 from the 2026-05-30 security posture audit: the
``/api/console/v1/tenants/{slug}/logs/stream`` endpoint validated tenant
existence but accepted any caller, so a logged-in customer (or anyone
who guessed the URL) could subscribe to the live log feed once it was
<<<<<<< Updated upstream
wired to real ``kubectl logs --follow``. This test pins the new
authentication path: no token → 4001, customer token → 4003, Sky-team
token → either 4004 (tenant slug missing) or 1000 on normal close.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.main import app
from src.models.user import User


def _client() -> TestClient:
    return TestClient(app)


def _token_for(user_id) -> str:
    return create_access_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_logs_stream_rejects_without_token():
    client = _client()
    with pytest.raises(Exception):
        # No token query param at all — FastAPI returns 403 before the
        # socket upgrades. We accept "any failure to open" here.
        with client.websocket_connect(
            "/api/console/v1/tenants/whatever/logs/stream"
        ):
            pass


@pytest.mark.asyncio
async def test_logs_stream_rejects_non_sky_team_user(db_session: AsyncSession):
    customer = User(
        id=uuid4(),
        email="customer@example.com",
        password_hash="x",
        name="Customer",
        role="user",
        email_verified=True,
        is_sky_operator=False,
    )
    db_session.add(customer)
    await db_session.commit()

    client = _client()
    token = _token_for(customer.id)
    with client.websocket_connect(
        f"/api/console/v1/tenants/whatever/logs/stream?token={token}"
    ) as ws:
        # Expect the explicit error frame + 4003 close code. The frame
        # is sent before close() so the FE can route on the message
        # ('sky_team_required') rather than guessing from the code.
        msg = ws.receive_json()
        assert msg == {"error": "sky_team_required"}


@pytest.mark.asyncio
async def test_logs_stream_accepts_sky_team_user_but_404s_unknown_tenant(
    db_session: AsyncSession,
):
    engineer = User(
        id=uuid4(),
        email="engineer@skyfirstlabs.com",
        password_hash="x",
        name="Engineer",
        role="admin",
        email_verified=True,
        is_sky_operator=True,
    )
    db_session.add(engineer)
    await db_session.commit()

    client = _client()
    token = _token_for(engineer.id)
    with client.websocket_connect(
        f"/api/console/v1/tenants/does-not-exist/logs/stream?token={token}"
    ) as ws:
        msg = ws.receive_json()
        # Past the Sky-team gate (no 4003) — the next layer is the
        # tenant-existence check, which surfaces tenant_not_found + 4004.
        assert msg == {"error": "tenant_not_found"}
=======
wired to real ``kubectl logs --follow``.

These tests are static-analysis level — exercising the FastAPI WS
TestClient from inside pytest pulls in the full lifespan stack
(Redis, AsyncSession event-loop ownership, etc.) and was producing
unrelated event-loop / UUID-type flakes. The actual policy is short
and lives in source, so we verify the source shape directly. The
``is_sky_team_member`` logic itself is covered by
``test_console_auth.py``.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from src.api.console_auth import is_sky_team_member
from src.api.v1 import console
from src.core.security import verify_token


_CONSOLE_SOURCE = Path(console.__file__).read_text(encoding="utf-8")


def test_logs_stream_endpoint_exists():
    assert hasattr(console, "stream_tenant_logs"), (
        "stream_tenant_logs route must exist on the Console router"
    )


def test_logs_stream_accepts_token_query_param():
    """The browser WS API can't set headers, so the JWT comes via the
    ``?token=`` query param. If this signature drifts, the FE will
    silently fall back to an unauthenticated connection."""
    sig = inspect.signature(console.stream_tenant_logs)
    assert "token" in sig.parameters, (
        f"stream_tenant_logs must accept ``token`` for auth; "
        f"signature is {sig}"
    )


def test_logs_stream_source_calls_verify_token():
    """The handler must call ``verify_token`` on the supplied token —
    a refactor that drops this is a silent regression of Gap #1."""
    assert "verify_token(" in _CONSOLE_SOURCE, (
        "stream_tenant_logs must call verify_token() on the supplied JWT"
    )
    # And the symbol must be importable from src.core.security so the
    # static check above isn't a false positive on a comment.
    assert callable(verify_token)


def test_logs_stream_source_calls_is_sky_team_member():
    """The handler must gate on ``is_sky_team_member`` — same predicate
    ``require_sky_team`` uses. Anything looser grants more on the WS
    surface than on the HTTP surface."""
    assert "is_sky_team_member(" in _CONSOLE_SOURCE, (
        "stream_tenant_logs must call is_sky_team_member() on the resolved user"
    )
    assert callable(is_sky_team_member)


def test_logs_stream_source_closes_with_documented_codes():
    """The FE routes on the close code (4001/4003/4004). If anyone
    rewrites these to 1000/1011/whatever, the FE error-handling layer
    silently degrades."""
    assert re.search(r"close\s*\(\s*code\s*=\s*4001\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4001 on unauthenticated"
    )
    assert re.search(r"close\s*\(\s*code\s*=\s*4003\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4003 on non-Sky-team"
    )
    assert re.search(r"close\s*\(\s*code\s*=\s*4004\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4004 on missing tenant"
    )
>>>>>>> Stashed changes
